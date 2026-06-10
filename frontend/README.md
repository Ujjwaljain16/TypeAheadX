# TypeAheadX Frontend

This is the Next.js frontend for **TypeAheadX**, designed to provide a highly responsive, Google-like autocomplete search experience while remaining robust against race conditions and network spam.

## Tech Stack
- **Framework**: Next.js 15 (App Router)
- **Library**: React 19
- **Styling**: Tailwind CSS
- **Icons**: Lucide React

## Engineering Highlights

While the backend handles the heavy lifting of consistent hashing and distributed caching, the frontend is engineered to handle chaotic user input efficiently:

1. **Debouncing (250ms)**: User keystrokes are debounced to ensure we don't spam the API with 6 requests for a 6-letter word. It waits until the user pauses typing before fetching.
2. **Request Cancellation (`AbortController`)**: If a user types "iphone", deletes it, and types "samsung" rapidly, the network might return "iphone" results *after* "samsung" results. We use `AbortController` to cancel in-flight requests, guaranteeing the UI never displays stale data from a race condition.
3. **Trending Feedback Loop**: Clicking a suggestion (or hitting Enter) fires a `POST` request to the backend, feeding the async write-buffer and dynamically updating the global popularity rankings.

## Getting Started

First, ensure the FastAPI backend is running on `http://localhost:8000`.

Then, install dependencies and start the development server:

```bash
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to interact with the search engine.
