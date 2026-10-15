import { afterEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useSuggestions } from "@/hooks/useSuggestions";
import { ApiClient } from "@/lib/api";
import type { SuggestResponse } from "@/types/suggestion";

function deferred() {
  let resolve!: (v: SuggestResponse) => void;
  let reject!: (e: Error) => void;
  const promise = new Promise<SuggestResponse>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const response = (prefix: string, ...queries: string[]): SuggestResponse => ({
  prefix,
  total_results: queries.length,
  suggestions: queries.map((q, i) => ({ query: q, historical_count: 100 - i })),
});

afterEach(() => vi.restoreAllMocks());

describe("useSuggestions", () => {
  it("shows nothing and does not fetch for an empty query", () => {
    const spy = vi.spyOn(ApiClient, "suggest");
    const { result } = renderHook(({ q }) => useSuggestions(q), { initialProps: { q: "   " } });
    expect(spy).not.toHaveBeenCalled();
    expect(result.current).toEqual({ suggestions: [], isLoading: false, error: null });
  });

  it("is loading until the response for the CURRENT query arrives", async () => {
    const d = deferred();
    vi.spyOn(ApiClient, "suggest").mockReturnValue(d.promise);
    const { result } = renderHook(({ q }) => useSuggestions(q), { initialProps: { q: "iph" } });
    expect(result.current.isLoading).toBe(true);
    await act(async () => d.resolve(response("iph", "iphone", "iphone 15")));
    expect(result.current.isLoading).toBe(false);
    expect(result.current.suggestions.map((s) => s.query)).toEqual(["iphone", "iphone 15"]);
  });

  it("a late response for a superseded query can never overwrite the newer one (out-of-order responses)", async () => {
    const slow = deferred();
    const fast = deferred();
    const spy = vi.spyOn(ApiClient, "suggest").mockImplementation((q: string) => (q === "ip" ? slow.promise : fast.promise));
    const { result, rerender } = renderHook(({ q }) => useSuggestions(q), { initialProps: { q: "ip" } });
    rerender({ q: "iph" });
    expect(spy).toHaveBeenCalledTimes(2);

    await act(async () => fast.resolve(response("iph", "iphone")));
    expect(result.current.suggestions.map((s) => s.query)).toEqual(["iphone"]);

    await act(async () => slow.resolve(response("ip", "ipad", "ipod")));   // arrives late
    expect(result.current.suggestions.map((s) => s.query)).toEqual(["iphone"]);
    expect(result.current.isLoading).toBe(false);
  });

  it("ignores AbortError (a newer request is taking over) but surfaces real errors", async () => {
    const aborted = deferred();
    vi.spyOn(ApiClient, "suggest").mockReturnValue(aborted.promise);
    const { result, rerender } = renderHook(({ q }) => useSuggestions(q), { initialProps: { q: "a" } });
    const err = new Error("aborted");
    err.name = "AbortError";
    await act(async () => aborted.reject(err));
    expect(result.current.error).toBeNull();
    expect(result.current.isLoading).toBe(true);        // still waiting for the request that replaced it

    const failing = deferred();
    vi.spyOn(ApiClient, "suggest").mockReturnValue(failing.promise);
    rerender({ q: "ab" });
    await act(async () => failing.reject(new Error("API error: Service Unavailable")));
    expect(result.current.error).toBe("API error: Service Unavailable");
    expect(result.current.suggestions).toEqual([]);
    expect(result.current.isLoading).toBe(false);
  });

  it("clearing the input hides results immediately, even while a response is still in flight", async () => {
    const d = deferred();
    vi.spyOn(ApiClient, "suggest").mockReturnValue(d.promise);
    const { result, rerender } = renderHook(({ q }) => useSuggestions(q), { initialProps: { q: "iph" } });
    rerender({ q: "" });
    await act(async () => d.resolve(response("iph", "iphone")));    // stale; must not reappear
    expect(result.current).toEqual({ suggestions: [], isLoading: false, error: null });
  });

  it("does not fetch for the text the user just selected", () => {
    const spy = vi.spyOn(ApiClient, "suggest");
    const { result } = renderHook(({ q, skip }) => useSuggestions(q, skip), { initialProps: { q: "iphone 15", skip: "iphone 15" as string | null } });
    expect(spy).not.toHaveBeenCalled();
    expect(result.current.isLoading).toBe(false);
  });
});
