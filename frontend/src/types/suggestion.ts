export interface Suggestion {
    query: string;
    historical_count: number;
}

export interface SuggestResponse {
    prefix: string;
    total_results: number;
    suggestions: Suggestion[];
}
