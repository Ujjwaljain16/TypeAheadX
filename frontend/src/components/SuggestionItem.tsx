import { Suggestion } from "@/types/suggestion";

interface SuggestionItemProps {
  suggestion: Suggestion;
  isSelected: boolean;
  onSelect: (query: string) => void;
  id: string;
}

export function SuggestionItem({ suggestion, isSelected, onSelect, id }: SuggestionItemProps) {
  return (
    <li
      id={id}
      role="option"
      aria-selected={isSelected}
      onClick={() => onSelect(suggestion.query)}
      className={`px-4 py-3 cursor-pointer flex items-center justify-between transition-all duration-200 ${
        isSelected ? "bg-indigo-50 text-indigo-700" : "hover:bg-slate-50 text-slate-700"
      }`}
    >
      <div className="flex items-center gap-3">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          className={`h-4 w-4 ${isSelected ? "text-indigo-400" : "text-slate-400"}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
        <span className="font-medium text-sm">{suggestion.query}</span>
      </div>
      <span className="text-xs text-slate-400 bg-slate-100 px-2 py-1 rounded-full font-medium">
        {suggestion.historical_count > 1000 
          ? `${(suggestion.historical_count / 1000).toFixed(1)}k` 
          : suggestion.historical_count}
      </span>
    </li>
  );
}
