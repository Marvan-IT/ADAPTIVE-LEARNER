import { motion } from "framer-motion";
import { cn } from "./lib/utils";

const variantClasses = {
  elevated:
    "bg-[var(--color-surface)] border border-[var(--color-border)] shadow-[var(--shadow-md)] transition-all rounded-2xl",
  flat:
    "bg-[var(--color-surface-2)] rounded-2xl",
  "list-item":
    "flex flex-row items-center border-b border-[var(--color-border)] hover:bg-[var(--table-row-hover)] transition-colors rounded-none",
};

/**
 * @param {"elevated"|"flat"|"list-item"} [props.variant="elevated"] - Card style variant
 * @param {string} [props.className]
 * @param {React.ReactNode} [props.children]
 */
export default function Card({ variant = "elevated", className, children, ...rest }) {
  const isElevated = variant === "elevated";

  const Component = isElevated ? motion.div : "div";

  const motionProps = isElevated
    ? {
        whileHover: { y: -3, boxShadow: "0 8px 24px rgba(0,0,0,0.08)" },
        transition: { type: "spring", stiffness: 200, damping: 20 },
      }
    : {};

  return (
    <Component
      className={cn(variantClasses[variant] ?? variantClasses.elevated, className)}
      {...motionProps}
      {...rest}
    >
      {children}
    </Component>
  );
}

/**
 * @param {string} [props.className]
 * @param {React.ReactNode} [props.children]
 */
export function CardHeader({ className, children, ...rest }) {
  return (
    <div
      className={cn(
        "px-[var(--sp-6)] pt-[var(--sp-6)] pb-[var(--sp-2)]",
        className
      )}
      {...rest}
    >
      {children}
    </div>
  );
}

/**
 * @param {string} [props.className]
 * @param {React.ReactNode} [props.children]
 */
export function CardContent({ className, children, ...rest }) {
  return (
    <div
      className={cn(
        "px-[var(--sp-6)] py-[var(--sp-4)]",
        className
      )}
      {...rest}
    >
      {children}
    </div>
  );
}

/**
 * @param {string} [props.className]
 * @param {React.ReactNode} [props.children]
 */
export function CardFooter({ className, children, ...rest }) {
  return (
    <div
      className={cn(
        "px-[var(--sp-6)] pb-[var(--sp-6)] pt-[var(--sp-2)] flex items-center gap-3",
        className
      )}
      {...rest}
    >
      {children}
    </div>
  );
}
