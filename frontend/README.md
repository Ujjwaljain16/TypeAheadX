# TypeAheadX frontend

Next.js 16 (App Router) · React 19 · Tailwind 4 · TypeScript. A single-page autocomplete box built to behave well with chaotic input and a slow or failing backend.

## Behaviour
1. **Debounce (250 ms)** — one request per pause in typing, not one per keystroke (`hooks/useDebounce.ts`).
2. **Cancellation** — a shared `AbortController` aborts the previous in-flight request when a new one starts; an `isMounted` guard in the effect cleanup ensures a late response can never overwrite a newer one (`lib/api.ts`, `hooks/useSuggestions.ts`). Verified by code inspection only — there are no automated frontend tests yet.
3. **Selection feedback** — clicking a suggestion or pressing Enter posts the query to `POST /search` (the write buffer); the text just selected is not re-fetched.
4. **Keyboard & a11y** — `role="combobox"` / `listbox` / `option`, `aria-activedescendant`, `aria-autocomplete="list"`, Up/Down/Enter/Escape. Not done: a live region announcing loading/error states.
5. Input is limited to 64 characters (the backend rejects longer prefixes with 400).

## Run
```bash
npm ci
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev      # default API URL is http://localhost:8000
npm run lint && npx tsc --noEmit && npm run build
```
CI runs install, type-check and build on Linux. `npm run lint` currently reports two pre-existing `react-hooks/set-state-in-effect` errors (non-gating in CI; the effects reset UI state when the query becomes empty).

`next` is pinned to a published release (16.2.7); the original pin to a preview build had no SWC binaries and forced a Windows-only dependency that broke `npm ci` everywhere else.
