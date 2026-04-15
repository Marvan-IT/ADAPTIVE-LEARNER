import { cn } from "./lib/utils";

/**
 * Variant classes using CSS color-mix for transparent tinted backgrounds.
 * Each variant defines: bg (12% tint), text color, border (30% opacity).
 */
const variantClasses = {
  success:
    "bg-[color-mix(in_srgb,var(--color-success)_12%,transparent)] text-[var(--color-success)] border border-[color-mix(in_srgb,var(--color-success)_30%,transparent)]",
  warning:
    "bg-[color-mix(in_srgb,var(--color-warning)_12%,transparent)] text-[var(--color-warning)] border border-[color-mix(in_srgb,var(--color-warning)_30%,transparent)]",
  danger:
    "bg-[color-mix(in_srgb,var(--color-danger)_12%,transparent)] text-[var(--color-danger)] border border-[color-mix(in_srgb,var(--color-danger)_30%,transparent)]",
  info:
    "bg-[color-mix(in_srgb,var(--color-info)_12%,transparent)] text-[var(--color-info)] border border-[color-mix(in_srgb,var(--color-info)_30%,transparent)]",
  neutral:
    "bg-[color-mix(in_srgb,var(--color-text-muted)_12%,transparent)] text-[var(--color-text-muted)] border border-[color-mix(in_srgb,var(--color-text-muted)_30%,transparent)]",
  mastered:
    "bg-[color-mix(in_srgb,var(--color-success)_15%,transparent)] text-[var(--xp-gold)] border border-[color-mix(in_srgb,var(--xp-gold)_30%,transparent)]",
  available:
    "bg-[color-mix(in_srgb,var(--color-primary)_12%,transparent)] text-[var(--color-primary)] border border-[color-mix(in_srgb,var(--color-primary)_30%,transparent)]",
  locked:
    "bg-[color-mix(in_srgb,var(--node-locked)_20%,transparent)] text-[var(--node-locked)] border border-[color-mix(in_srgb,var(--node-locked)_30%,transparent)]",
  weak:
    "bg-[color-mix(in_srgb,var(--color-warning)_12%,transparent)] text-[var(--color-warning)] border border-[color-mix(in_srgb,var(--color-warning)_30%,transparent)]",
  new:
    "bg-[color-mix(in_srgb,#f97316_12%,transparent)] text-[#f97316] border border-[color-mix(in_srgb,#f97316_30%,transparent)]",
};

const sizeClasses = {
  sm: "text-[0.72rem] px-2 py-0.5",
  md: "text-xs px-2.5 py-1",
};

/**
 * @param {"success"|"warning"|"danger"|"info"|"neutral"|"mastered"|"available"|"locked"|"weak"|"new"} [props.variant="neutral"] - Color variant
 * @param {"sm"|"md"} [props.size="sm"] - Badge size
 * @param {string} [props.className]
 * @param {React.ReactNode} [props.children]
 */
export default function Badge({ variant = "neutral", size = "sm", className, children, ...rest }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-[var(--radius-full)] font-bold",
        variantClasses[variant] ?? variantClasses.neutral,
        sizeClasses[size] ?? sizeClasses.sm,
        className
      )}
      {...rest}
    >
      {children}
    </span>
  );
}
