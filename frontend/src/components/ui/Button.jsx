import { Loader } from "lucide-react";

const VARIANTS = {
  primary: {
    bg: "var(--color-primary)",
    color: "#fff",
    border: "none",
    hover: "brightness(1.1)",
  },
  secondary: {
    bg: "var(--color-primary-light)",
    color: "var(--color-primary)",
    border: "none",
    hover: "brightness(0.95)",
  },
  ghost: {
    bg: "transparent",
    color: "var(--color-text-muted)",
    border: "1.5px solid var(--color-border)",
    hover: "brightness(0.9)",
  },
  danger: {
    bg: "var(--color-danger)",
    color: "#fff",
    border: "none",
    hover: "brightness(1.1)",
  },
};

const SIZES = {
  sm: { padding: "0.35rem 0.75rem", fontSize: "0.8rem",  gap: "0.3rem" },
  md: { padding: "0.65rem 1.25rem", fontSize: "0.95rem", gap: "0.45rem" },
  lg: { padding: "0.85rem 1.75rem", fontSize: "1.05rem", gap: "0.55rem" },
};

export default function Button({
  children,
  variant = "primary",
  size = "md",
  loading = false,
  disabled = false,
  onClick,
  type = "button",
  style: extraStyle = {},
  "aria-label": ariaLabel,
  ...rest
}) {
  const v = VARIANTS[variant] || VARIANTS.primary;
  const s = SIZES[size] || SIZES.md;
  const isDisabled = disabled || loading;

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={isDisabled}
      aria-label={ariaLabel}
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        gap: s.gap,
        padding: s.padding,
        fontSize: s.fontSize,
        fontWeight: 700,
        fontFamily: "inherit",
        borderRadius: "var(--radius-md)",
        border: v.border,
        backgroundColor: v.bg,
        color: v.color,
        cursor: isDisabled ? "not-allowed" : "pointer",
        opacity: isDisabled && !loading ? 0.45 : 1,
        transition: "transform var(--motion-fast), box-shadow var(--motion-fast), filter var(--motion-fast)",
        boxShadow: variant === "primary" ? "var(--shadow-sm)" : "none",
        ...extraStyle,
      }}
      onMouseEnter={(e) => {
        if (!isDisabled) {
          e.currentTarget.style.transform = "scale(1.02)";
          e.currentTarget.style.boxShadow = variant === "primary" ? "var(--shadow-md)" : "none";
        }
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.transform = "scale(1)";
        e.currentTarget.style.boxShadow = variant === "primary" ? "var(--shadow-sm)" : "none";
      }}
      onMouseDown={(e) => {
        if (!isDisabled) e.currentTarget.style.transform = "scale(0.97)";
      }}
      onMouseUp={(e) => {
        if (!isDisabled) e.currentTarget.style.transform = "scale(1.02)";
      }}
      {...rest}
    >
      {loading && (
        <Loader
          size={size === "sm" ? 13 : size === "lg" ? 18 : 15}
          style={{ animation: "spin 1s linear infinite", flexShrink: 0 }}
        />
      )}
      {children}
    </button>
  );
}
