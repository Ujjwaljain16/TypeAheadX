import { useState, useEffect, useRef } from "react";
import { Suggestion } from "@/types/suggestion";
import { ApiClient } from "@/lib/api";

/**
 * @param skipQuery a query for which no request should be made (the text the user just selected);
 *                  passing null means "fetch for everything".
 */
export function useSuggestions(debouncedQuery: string, skipQuery: string | null = null) {
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Kept in a ref so that changing it does not re-run the fetch effect with a stale debounced value.
  const skipRef = useRef<string | null>(skipQuery);
  useEffect(() => {
    skipRef.current = skipQuery;
  }, [skipQuery]);

  useEffect(() => {
    // The user just selected this text: fetching suggestions for it would be a wasted request.
    if (skipRef.current !== null && debouncedQuery === skipRef.current) {
      return;
    }

    // If the query is empty, we just clear everything.
    if (!debouncedQuery.trim()) {
      setSuggestions([]);
      setIsLoading(false);
      setError(null);
      return;
    }

    let isMounted = true;
    setIsLoading(true);
    setError(null);

    ApiClient.suggest(debouncedQuery)
      .then((data) => {
        if (isMounted) {
          setSuggestions(data.suggestions);
          setIsLoading(false);
        }
      })
      .catch((err) => {
        // We ignore abort errors entirely (since a new request is taking over)
        if (err.name === "AbortError") {
          return;
        }
        if (isMounted) {
          setError(err.message || "An error occurred fetching suggestions.");
          setSuggestions([]);
          setIsLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [debouncedQuery]);

  return { suggestions, isLoading, error };
}
