import { useState, useEffect, useRef } from "react";
import { Suggestion } from "@/types/suggestion";
import { ApiClient } from "@/lib/api";

interface Result {
  /** the debounced query this result belongs to */
  query: string;
  suggestions: Suggestion[];
  error: string | null;
}

const EMPTY: Result = { query: "", suggestions: [], error: null };

/**
 * Fetches suggestions for the debounced query.
 *
 * State is stored together with the query it answers and everything else is *derived* during render:
 *  - an empty query shows nothing (no state reset needed),
 *  - `isLoading` is simply "the stored result is not for the current query",
 *  - a late response can never overwrite a newer one: the effect cleanup flips `isMounted` for superseded
 *    queries, and ApiClient additionally aborts the previous in-flight request.
 *
 * @param skipQuery a query for which no request should be made (the text the user just selected);
 *                  null means "fetch for everything".
 */
export function useSuggestions(debouncedQuery: string, skipQuery: string | null = null) {
  const [result, setResult] = useState<Result>(EMPTY);

  // Kept in a ref so that changing it does not re-run the fetch effect with a stale debounced value.
  const skipRef = useRef<string | null>(skipQuery);
  useEffect(() => {
    skipRef.current = skipQuery;
  }, [skipQuery]);

  useEffect(() => {
    // Nothing to fetch for an empty query, or for the text the user just selected.
    if (!debouncedQuery.trim()) return;
    if (skipRef.current !== null && debouncedQuery === skipRef.current) return;

    let isMounted = true;
    ApiClient.suggest(debouncedQuery)
      .then((data) => {
        if (isMounted) setResult({ query: debouncedQuery, suggestions: data.suggestions, error: null });
      })
      .catch((err: unknown) => {
        // A newer request is taking over: its result will arrive instead.
        if (err instanceof Error && err.name === "AbortError") return;
        if (isMounted) {
          const message = err instanceof Error && err.message ? err.message : "An error occurred fetching suggestions.";
          setResult({ query: debouncedQuery, suggestions: [], error: message });
        }
      });

    return () => {
      isMounted = false;
    };
  }, [debouncedQuery]);

  const isEmpty = !debouncedQuery.trim();
  const isSkipped = skipQuery !== null && debouncedQuery === skipQuery;
  const isCurrent = result.query === debouncedQuery;

  return {
    suggestions: isEmpty ? EMPTY.suggestions : result.suggestions,
    isLoading: !isEmpty && !isSkipped && !isCurrent,
    error: !isEmpty && isCurrent ? result.error : null,
  };
}
