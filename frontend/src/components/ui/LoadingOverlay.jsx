export default function LoadingOverlay({ isLoading, children }) {
  if (!isLoading) return children;
  return (
    <div className="relative">
      <div className="pointer-events-none select-none">{children}</div>
      <div className="absolute inset-0 flex items-center justify-center rounded-lg backdrop-blur-sm bg-slate-950/40 z-10">
        <svg
          className="animate-spin h-8 w-8 text-indigo-400"
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
        >
          <circle
            className="opacity-25"
            cx="12"
            cy="12"
            r="10"
            stroke="currentColor"
            strokeWidth="4"
          />
          <path
            className="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
          />
        </svg>
      </div>
    </div>
  );
}
