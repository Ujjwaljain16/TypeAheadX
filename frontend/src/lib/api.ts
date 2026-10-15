import { SuggestResponse } from "@/types/suggestion";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/** Longest prefix the backend accepts (MAX_PREFIX_LENGTH); longer input would only produce a 400. */
export const MAX_QUERY_LENGTH = 64;

export class ApiClient {
  private static suggestController: AbortController | null = null;

  /**
   * Fetches suggestions for a given prefix.
   * Cancels any previously inflight suggest request to prevent stale renders.
   */
  static async suggest(query: string): Promise<SuggestResponse> {
    // Abort the previous request if it's still running
    if (this.suggestController) {
      this.suggestController.abort();
    }

    // Create a new controller for the current request
    this.suggestController = new AbortController();

    try {
      const response = await fetch(`${API_URL}/suggest?q=${encodeURIComponent(query)}`, {
        signal: this.suggestController.signal,
      });

      if (!response.ok) {
        throw new Error(`API error: ${response.statusText}`);
      }

      const data: SuggestResponse = await response.json();
      return data;
    } catch (error: unknown) {
      if (error instanceof Error && error.name === "AbortError") {
        // We gracefully handle aborts so they can be filtered by the caller
        throw error;
      }
      console.error("Failed to fetch suggestions:", error);
      throw error;
    }
  }

  /** Fire-and-forget: records the selected query (it must use the same API base URL as suggest). */
  static async recordSearch(query: string): Promise<void> {
    try {
      await fetch(`${API_URL}/search`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query }),
      });
    } catch (err) {
      console.error("Failed to submit search:", err);
    }
  }
}
