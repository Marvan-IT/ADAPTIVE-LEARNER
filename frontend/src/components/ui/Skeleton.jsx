export default function Skeleton({ width = "100%", height = "1rem", style: extra = {} }) {
  return (
    <div
      className="skeleton-shimmer"
      style={{ width, height, ...extra }}
      aria-hidden="true"
    />
  );
}

export function CardSkeleton() {
  return (
    <div style={{
      backgroundColor: "var(--color-surface)",
      borderRadius: "var(--radius-lg)",
      border: "2px solid var(--color-border)",
      overflow: "hidden",
      padding: "1.5rem 1.75rem",
    }} aria-busy="true" aria-label="Loading card">
      {/* Header */}
      <Skeleton height="1.4rem" width="60%" style={{ marginBottom: "1rem" }} />
      {/* Content lines */}
      <Skeleton height="1rem" style={{ marginBottom: "0.6rem" }} />
      <Skeleton height="1rem" width="90%" style={{ marginBottom: "0.6rem" }} />
      <Skeleton height="1rem" width="75%" style={{ marginBottom: "1.5rem" }} />
      {/* Options */}
      <Skeleton height="2.8rem" style={{ marginBottom: "0.5rem", borderRadius: "var(--radius-full)" }} />
      <Skeleton height="2.8rem" style={{ marginBottom: "0.5rem", borderRadius: "var(--radius-full)" }} />
      <Skeleton height="2.8rem" style={{ borderRadius: "var(--radius-full)" }} />
    </div>
  );
}
