import LoadingIndicator from './LoadingIndicator';

export default function LoadingOverlay({ isLoading, children }) {
  if (!isLoading) return children;
  return (
    <div className="relative">
      <div className="pointer-events-none select-none">{children}</div>
      <div className="absolute inset-0 flex items-center justify-center rounded-lg backdrop-blur-sm bg-slate-950/40 z-10">
        <LoadingIndicator />
      </div>
    </div>
  );
}
