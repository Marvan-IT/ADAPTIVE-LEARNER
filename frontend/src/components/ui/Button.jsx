import { motion } from "framer-motion";
import { Loader2 } from "lucide-react";
import { cn } from "./lib/utils";

const variantClasses = {
  primary:
    "bg-[#EA580C] text-white hover:bg-[#C2410C] shadow-sm",
  secondary:
    "bg-[var(--color-surface-2)] text-[var(--color-text)] border border-[var(--color-border)] hover:bg-[var(--color-border)]",
  ghost:
    "bg-transparent text-[var(--color-text-muted)] hover:bg-[var(--color-surface-2)]",
  danger:
    "bg-[var(--color-danger)] text-white hover:brightness-110",
};

const sizeClasses = {
  sm: "h-8 px-3 text-xs gap-1.5",
  md: "h-10 px-4 text-sm gap-2",
  lg: "h-12 px-6 text-base gap-2.5",
};

const iconOnlySizeClasses = {
  sm: "h-8 w-8 px-0",
  md: "h-10 w-10 px-0",
  lg: "h-12 w-12 px-0",
};

/**
 * @param {"primary"|"secondary"|"ghost"|"danger"} [props.variant="primary"] - Visual style
 * @param {"sm"|"md"|"lg"} [props.size="md"] - Button size
 * @param {boolean} [props.loading] - Shows a spinner and disables interaction
 * @param {boolean} [props.disabled] - Disables the button
 * @param {boolean} [props.iconOnly] - Makes the button square (no horizontal padding)
 * @param {React.ReactNode} [props.icon] - Icon rendered before children
 * @param {string} [props.className] - Additional Tailwind classes
 * @param {React.ReactNode} [props.children]
 */
export default function Button({
  variant = "primary",
  size = "md",
  loading = false,
  disabled = false,
  iconOnly = false,
  icon,
  className,
  children,
  ...rest
}) {
  const isDisabled = disabled || loading;

  return (
    <motion.button
      whileHover={isDisabled ? {} : { scale: 1.02 }}
      whileTap={isDisabled ? {} : { scale: 0.97 }}
      disabled={isDisabled}
      className={cn(
        // Base
        "inline-flex items-center justify-center font-semibold rounded-[var(--btn-radius)] transition-colors",
        // Variant
        variantClasses[variant] ?? variantClasses.primary,
        // Size — icon-only removes horizontal padding and makes square
        iconOnly ? iconOnlySizeClasses[size] : sizeClasses[size],
        // Disabled / loading state
        isDisabled && "opacity-50 cursor-not-allowed pointer-events-none",
        // Focus ring
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--color-bg)]",
        className
      )}
      {...rest}
    >
      {loading ? (
        <Loader2 size={16} className="animate-spin" aria-hidden="true" />
      ) : (
        <>
          {icon && <span className="shrink-0">{icon}</span>}
          {children}
        </>
      )}
    </motion.button>
  );
}

export { Button };
