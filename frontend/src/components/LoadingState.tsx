import { useState, useEffect } from "react";

export function LoadingState() {
  const [show, setShow] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => {
      setShow(true);
    }, 100); // 100ms delay before showing to prevent flicker on fast responses

    return () => clearTimeout(timer);
  }, []);

  if (!show) return null;

  return (
    <div className="flex items-center justify-center p-4 text-slate-500">
      <div className="h-5 w-5 animate-spin rounded-full border-b-2 border-t-2 border-slate-500 mr-3"></div>
      <span className="text-sm">Loading suggestions...</span>
    </div>
  );
}
