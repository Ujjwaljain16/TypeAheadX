import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiClient, MAX_QUERY_LENGTH } from "@/lib/api";

type Pending = { signal: AbortSignal; resolve: (body: unknown) => void; url: string };

/** A fetch stub whose responses are resolved by the test; rejects with AbortError when the signal aborts. */
function stubFetch() {
  const pending: Pending[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      return new Promise((resolve, reject) => {
        const signal = init?.signal as AbortSignal;
        pending.push({
          url,
          signal,
          resolve: (body) => resolve({ ok: true, json: async () => body }),
        });
        signal?.addEventListener("abort", () => {
          const err = new Error("aborted");
          err.name = "AbortError";
          reject(err);
        });
      });
    }),
  );
  return pending;
}

describe("ApiClient.suggest", () => {
  let pending: Pending[];
  beforeEach(() => {
    pending = stubFetch();
    vi.spyOn(console, "error").mockImplementation(() => {});
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("aborts the previous in-flight request when a new one starts", async () => {
    const first = ApiClient.suggest("ip");
    const firstRejected = expect(first).rejects.toMatchObject({ name: "AbortError" });
    const second = ApiClient.suggest("iph");

    expect(pending[0].signal.aborted).toBe(true);
    expect(pending[1].signal.aborted).toBe(false);
    await firstRejected;

    pending[1].resolve({ prefix: "iph", total_results: 0, suggestions: [] });
    await expect(second).resolves.toMatchObject({ prefix: "iph" });
  });

  it("url-encodes the query", async () => {
    const p = ApiClient.suggest("a b&c=%");
    const aborted = expect(p).rejects.toMatchObject({ name: "AbortError" });
    expect(pending[0].url).toContain("/suggest?q=a%20b%26c%3D%25");
    ApiClient.suggest("next").catch(() => {});       // supersedes (aborts) the first call
    await aborted;
  });

  it("throws on a non-2xx response", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, statusText: "Service Unavailable" })));
    await expect(ApiClient.suggest("x")).rejects.toThrow("API error: Service Unavailable");
  });

  it("posts selections to the same API base URL", async () => {
    const fetchMock = vi.fn(async () => ({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    await ApiClient.recordSearch("iphone");
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toMatch(/\/search$/);
    expect(url).not.toContain("localhost:8000/search/");
    expect(JSON.parse(init.body as string)).toEqual({ query: "iphone" });
  });

  it("keeps the input limit in sync with the backend's MAX_PREFIX_LENGTH", () => {
    expect(MAX_QUERY_LENGTH).toBe(64);
  });
});
