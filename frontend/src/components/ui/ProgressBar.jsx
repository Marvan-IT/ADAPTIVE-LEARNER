import { motion } from "framer-motion";
import { cn } from "./lib/utils";

/** @type {Record<string, string>} */
const SIZE_CLASSES = {
  sm: "h-1.5",
  md: "h-[10px]",
  lg: "h-3.5",
};

/** @type {Record<string, string>} */
const COLOR_CLASSES = {
  primary: "bg-[var(--color-primary)]",
  success: "bg-[var(--color-success)]",
  warning: "bg-[var(--color-warning)]",
  danger:  "bg-[var(--color-danger)]",
};

/**
 * Horizontal progress bar with optional label, percentage, and mount animation.
 *
 * @param {{
 *   value: number,
 *   color?: "primary" | "success" | "warning" | "danger",
 *   size?: "sm" | "md" | "lg",
 *   label?: string,
 *   showPercent?: boolean,
 *   animated?: boolean,
 *   className?: string
 * }} props
 * @param {number}                                      props.value        - 0–100
 * @param {"primary"|"success"|"warning"|"danger"}    [props.color="primary"]
 * @param {"sm"|"md"|"lg"}                             [props.size="md"]
 * @param {string}                                     [props.label]       - Text above bar (left)
 * @param {boolean}                                    [props.showPercent=false] - Show percentage top-right
 * @param {boolean}                                    [props.animated=true]    - Animate fill on mount
 * @param {string}                                     [props.className]
 */
export default function ProgressBar({
  value = 0,
  color = "primary",
  size = "md",
  label,
  showPercent = false,
  animated = true,
  className,
}) {
  const clamped = Math.min(100, Math.max(0, value));

  const fillClass = COLOR_CLASSES[color] ?? COLOR_CLASSES.primary;
  const heightClass = SIZE_CLASSES[size] ?? SIZE_CLASSES.md;

  const showHeader = label || showPercent;

  return (
    <div className={cn("w-full", className)}>
      {showHeader && (
        <div className="flex items-center justify-between mb-1">
          {label && (
            <span className="text-sm text-[var(--color-text-muted)]">{label}</span>
          )}
          {showPercent && (
            <span className="text-sm text-[var(--color-text-muted)] ml-auto">
              {clamped}%
            </span>
          )}
        </div>
      )}

      {/* Track */}
      <div
        className={cn(
          "w-full rounded-[var(--radius-full)] bg-[var(--color-border)] overflow-hidden",
          heightClass
        )}
        role="progressbar"
        aria-valuenow={clamped}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label}
      >
        {animated ? (
          <motion.div
            className={cn("h-full rounded-[var(--radius-full)]", fillClass)}
            initial={{ width: 0 }}
            animate={{ width: `${clamped}%` }}
            transition={{ type: "spring", stiffness: 100, damping: 20 }}
          />
        ) : (
          <div
            className={cn("h-full rounded-[var(--radius-full)]", fillClass)}
            style={{ width: `${clamped}%` }}
          />
        )}
      </div>
    </div>
  );
}
