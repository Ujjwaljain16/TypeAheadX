"use client";

import { useState, useRef, useEffect, KeyboardEvent } from "react";
import { useDebounce } from "@/hooks/useDebounce";
import { useSuggestions } from "@/hooks/useSuggestions";
import { SuggestionDropdown } from "./SuggestionDropdown";

export function SearchInput() {
  const [query, setQuery] = useState("");
  const [isFocused, setIsFocused] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(-1);
  const [submittedQuery, setSubmittedQuery] = useState<string | null>(null);
  
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const debouncedQuery = useDebounce(query, 250);
  const { suggestions, isLoading, error } = useSuggestions(debouncedQuery);

  // Reset selected index when suggestions change
  useEffect(() => {
    setSelectedIndex(-1);
  }, [suggestions]);

  // Handle clicks outside the component to close the dropdown
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsFocused(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    const isOpen = isFocused && (query.length > 0 || isLoading);
    
    if (!isOpen) return;

    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIndex((prev) => 
        prev < suggestions.length - 1 ? prev + 1 : prev
      );
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIndex((prev) => (prev > -1 ? prev - 1 : -1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (selectedIndex >= 0 && selectedIndex < suggestions.length) {
        handleSelect(suggestions[selectedIndex].query);
      } else if (query.trim()) {
        handleSelect(query.trim());
      }
    } else if (e.key === "Escape") {
      setIsFocused(false);
      inputRef.current?.blur();
    }
  };

  const handleSelect = async (selectedQuery: string) => {
    setQuery(selectedQuery);
    setIsFocused(false);
    setSelectedIndex(-1);
    setSubmittedQuery(selectedQuery);

    try {
      // Fire and forget search submission
      await fetch("http://localhost:8000/api/search", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ query: selectedQuery }),
      });
    } catch (err) {
      console.error("Failed to submit search:", err);
    }
  };

  const showDropdown = isFocused && query.length > 0;

  return (
    <div className="w-full max-w-2xl mx-auto flex flex-col items-center">
      <div 
        ref={containerRef} 
        className="relative w-full"
      >
        <div 
          className={`relative flex items-center bg-white/80 backdrop-blur-md border ${
            showDropdown ? 'border-indigo-300 ring-4 ring-indigo-100 rounded-t-xl' : 'border-slate-200 hover:border-slate-300 rounded-xl shadow-sm'
          } transition-all duration-200 z-50`}
        >
          <div className="pl-4 text-slate-400">
            <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
          </div>
          <input
            ref={inputRef}
            type="text"
            role="combobox"
            aria-expanded={showDropdown}
            aria-controls="search-suggestions"
            aria-activedescendant={selectedIndex >= 0 ? `suggestion-${selectedIndex}` : undefined}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setIsFocused(true);
              setSubmittedQuery(null);
            }}
            onFocus={() => setIsFocused(true)}
            onKeyDown={handleKeyDown}
            placeholder="Search anything..."
            className="w-full py-4 pl-3 pr-4 bg-transparent outline-none text-slate-700 placeholder:text-slate-400"
            autoComplete="off"
          />
          
          {query && (
            <button 
              onClick={() => {
                setQuery("");
                inputRef.current?.focus();
              }}
              className="pr-4 text-slate-400 hover:text-slate-600 transition-colors"
              aria-label="Clear search"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
              </svg>
            </button>
          )}
        </div>

        <SuggestionDropdown
          isOpen={showDropdown}
          suggestions={suggestions}
          isLoading={isLoading}
          error={error}
          selectedIndex={selectedIndex}
          onSelect={handleSelect}
          debouncedQuery={debouncedQuery}
        />
      </div>

      {submittedQuery && (
        <div className="mt-8 p-6 bg-slate-50 border border-slate-200 rounded-xl w-full text-center animate-in fade-in slide-in-from-bottom-4 duration-300">
          <p className="text-slate-500 mb-2">Selected query:</p>
          <p className="text-2xl font-bold text-slate-800 mb-4">{submittedQuery}</p>
          <p className="text-sm text-emerald-500 font-medium">✅ Search recorded to backend buffer.</p>
        </div>
      )}
    </div>
  );
}
