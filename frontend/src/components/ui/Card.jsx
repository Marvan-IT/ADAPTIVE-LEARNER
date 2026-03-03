export default function Card({ children, className = "", elevated = false, ...props }) {
  return (
    <div
      className={`bg-[var(--color-surface)] border border-[var(--color-border)] rounded-[var(--radius-lg)] ${elevated ? 'shadow-[var(--shadow-lg)]' : 'shadow-[var(--shadow-sm)]'} ${className}`}
      {...props}
    >
      {children}
    </div>
  );
}
