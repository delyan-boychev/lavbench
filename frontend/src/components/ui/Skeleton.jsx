export default function Skeleton({ variant = 'text', width, height, count = 1, className = '' }) {
  const base = 'animate-pulse bg-slate-700/50 rounded';
  const variants = {
    text: 'h-4 w-full',
    circular: 'rounded-full',
    rectangular: 'h-24 w-full',
  };
  const style = {
    ...(width ? { width } : {}),
    ...(height ? { height } : {}),
  };
  const cls = `${base} ${variants[variant] || variants.text} ${className}`;
  return (
    <div className="flex flex-col gap-2" role="status" aria-label="Loading">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className={cls} style={style} />
      ))}
    </div>
  );
}
