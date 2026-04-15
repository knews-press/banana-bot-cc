export function Spinner({ className = "" }: { className?: string }) {
  return (
    <div
      className={`animate-spin rounded-full border-2 h-5 w-5 ${className}`}
      style={{ borderColor: "var(--border-strong)", borderTopColor: "var(--text-2)" }}
    />
  );
}
