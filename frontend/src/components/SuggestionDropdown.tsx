import { Suggestion } from "@/types/suggestion";
import { SuggestionItem } from "./SuggestionItem";
import { LoadingState } from "./LoadingState";
import { ErrorState } from "./ErrorState";

interface SuggestionDropdownProps {
  isOpen: boolean;
  suggestions: Suggestion[];
  isLoading: boolean;
  error: string | null;
  selectedIndex: number;
  onSelect: (query: string) => void;
  debouncedQuery: string;
}

export function SuggestionDropdown({
  isOpen,
  suggestions,
  isLoading,
  error,
  selectedIndex,
  onSelect,
  debouncedQuery,
}: SuggestionDropdownProps) {
  if (!isOpen) return null;

  return (
    <div 
      className="absolute top-full left-0 right-0 mt-2 bg-white rounded-xl shadow-xl border border-slate-100 overflow-hidden z-50 transition-all duration-200 origin-top"
      role="listbox"
      id="search-suggestions"
    >
      {error && <ErrorState message={error} />}
      
      {isLoading && !error && <LoadingState />}
      
      {!isLoading && !error && suggestions.length > 0 && (
        <ul className="max-h-80 overflow-y-auto py-1">
          {suggestions.map((suggestion, index) => (
            <SuggestionItem
              key={suggestion.query}
              id={`suggestion-${index}`}
              suggestion={suggestion}
              isSelected={index === selectedIndex}
              onSelect={onSelect}
            />
          ))}
        </ul>
      )}

      {!isLoading && !error && suggestions.length === 0 && debouncedQuery && (
        <div className="p-4 text-center text-sm text-slate-500">
          No results found for "<span className="font-semibold">{debouncedQuery}</span>"
        </div>
      )}
    </div>
  );
}
