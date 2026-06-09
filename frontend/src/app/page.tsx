import { SearchInput } from "@/components/SearchInput";

export default function Home() {
  return (
    <main className="min-h-screen bg-gradient-to-b from-slate-50 to-slate-100 flex flex-col items-center pt-32 px-4 font-sans">
      <div className="w-full max-w-3xl flex flex-col items-center">
        <h1 className="text-4xl md:text-6xl font-extrabold text-slate-800 tracking-tight mb-4 text-center">
          <span className="text-transparent bg-clip-text bg-gradient-to-r from-indigo-500 to-purple-600">
            TypeAheadX
          </span>
        </h1>
        <p className="text-lg text-slate-500 mb-12 text-center max-w-xl">
          Lightning-fast prefix suggestions powered by PostgreSQL. Type below to see real-time historical search patterns.
        </p>

        <SearchInput />

      </div>
      
      <div className="fixed bottom-8 text-sm text-slate-400 font-medium tracking-wide">
        PHASE 2 • USER SEARCH EXPERIENCE
      </div>
    </main>
  );
}
