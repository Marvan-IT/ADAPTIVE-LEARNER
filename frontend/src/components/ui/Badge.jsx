const BADGE_VARIANTS = {
  success: { bg: "rgba(34,197,94,0.12)",  color: "#16a34a", border: "#86efac" },
  warning: { bg: "rgba(245,158,11,0.12)", color: "#d97706", border: "#fcd34d" },
  danger:  { bg: "rgba(239,68,68,0.12)",  color: "#dc2626", border: "#fca5a5" },
  info:    { bg: "var(--color-primary-light)", color: "var(--color-primary)", border: "var(--color-primary)" },
  neutral: { bg: "var(--color-border)",    color: "var(--color-text-muted)", border: "var(--color-border)" },
};

export default function Badge({ children, variant = "neutral", style: extra = {} }) {
  const v = BADGE_VARIANTS[variant] || BADGE_VARIANTS.neutral;
  return (
    <span style={{
      display: "inline-flex",
      alignItems: "center",
      gap: "0.25rem",
      padding: "0.15rem 0.55rem",
      borderRadius: "var(--radius-full)",
      backgroundColor: v.bg,
      color: v.color,
      border: `1px solid ${v.border}`,
      fontSize: "0.72rem",
      fontWeight: 700,
      ...extra,
    }}>
      {children}
    </span>
  );
}
