import { useState, useEffect } from "react";
import { Suggestion } from "@/types/suggestion";
import { ApiClient } from "@/lib/api";

export function useSuggestions(debouncedQuery: string) {
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
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
