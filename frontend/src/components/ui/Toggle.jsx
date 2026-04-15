import { motion } from "framer-motion";
import { cn } from "./lib/utils";

/**
 * @param {boolean} props.checked
 * @param {function} props.onChange - Called with the new checked value
 * @param {boolean} [props.disabled]
 * @param {string} [props.label] - Optional label rendered beside the toggle
 * @param {string} [props.id]
 * @param {string} [props.className]
 */
export default function Toggle({
  checked,
  onChange,
  disabled = false,
  label,
  id,
  className,
}) {
  function handleClick() {
    if (!disabled) onChange(!checked);
  }

  const button = (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={handleClick}
      className={cn(
        "inline-flex items-center px-0.5 w-[52px] h-7 rounded-[var(--radius-full)] transition-colors",
        checked
          ? "bg-[var(--toggle-active)]"
          : "bg-[var(--toggle-inactive)]",
        checked ? "justify-end" : "justify-start",
        disabled && "opacity-50 cursor-not-allowed",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)] focus-visible:ring-offset-2",
        !label && className
      )}
    >
      <motion.span
        layout
        transition={{ type: "spring", stiffness: 500, damping: 35 }}
        className="size-6 rounded-full bg-white shadow-sm"
      />
    </button>
  );

  if (!label) return button;

  return (
    <span className={cn("inline-flex items-center gap-3", className)}>
      <span className="text-sm text-[var(--color-text)] select-none">
        {label}
      </span>
      {button}
    </span>
  );
}
