import { useState } from "react";
import { Eye, EyeOff, Search, X } from "lucide-react";
import { cn } from "./lib/utils";

/**
 * @param {"text"|"email"|"password"|"search"|"number"} [props.type="text"] - Input type
 * @param {string} [props.error] - Error message displayed below the input
 * @param {React.ReactNode} [props.icon] - Icon placed in the left slot
 * @param {boolean} [props.clearable] - For search type: shows an X button to clear value
 * @param {string} [props.label] - Label rendered above the input
 * @param {string} [props.id] - Input id (also links the label)
 * @param {string} [props.value]
 * @param {function} [props.onChange]
 * @param {string} [props.placeholder]
 * @param {boolean} [props.disabled]
 * @param {boolean} [props.required]
 * @param {string} [props.className] - Applied to the outer wrapper div
 */
export default function Input({
  type = "text",
  error,
  icon,
  clearable = false,
  label,
  id,
  value,
  onChange,
  placeholder,
  disabled = false,
  required = false,
  className,
  ...rest
}) {
  const [showPassword, setShowPassword] = useState(false);

  const isPassword = type === "password";
  const isSearch = type === "search";

  // Determine effective input type
  const resolvedType = isPassword ? (showPassword ? "text" : "password") : type;

  // Determine whether a left icon should be shown
  const hasLeftIcon = !!icon || isSearch;

  // Determine whether a right control exists
  const hasRightControl = isPassword || (isSearch && clearable && value);

  return (
    <div className={cn("flex flex-col", className)}>
      {label && (
        <label
          htmlFor={id}
          className="block text-sm font-medium text-[var(--color-text)] mb-1.5"
        >
          {label}
          {required && (
            <span className="ms-1 text-[var(--color-danger)]" aria-hidden="true">
              *
            </span>
          )}
        </label>
      )}

      <div className="relative">
        {/* Left icon: custom icon takes priority; search falls back to Search icon */}
        {hasLeftIcon && (
          <span
            className="absolute start-3 top-1/2 -translate-y-1/2 text-[var(--color-text-muted)] pointer-events-none"
            aria-hidden="true"
          >
            {icon ?? <Search size={16} />}
          </span>
        )}

        <input
          id={id}
          type={resolvedType}
          value={value}
          onChange={onChange}
          placeholder={placeholder}
          disabled={disabled}
          required={required}
          aria-invalid={error ? "true" : undefined}
          aria-describedby={error && id ? `${id}-error` : undefined}
          className={cn(
            // Base
            "w-full h-12 rounded-xl border-2 border-slate-200 bg-[var(--input-bg)] text-[var(--color-text)] px-3 text-sm transition-colors",
            "placeholder:text-[var(--color-text-muted)]",
            // Focus
            "focus:outline-none focus:ring-2 focus:ring-[var(--color-primary-light)] focus:border-[var(--color-primary)]",
            // Error override
            error && "border-[var(--color-danger)] focus:ring-[var(--color-danger)] focus:border-[var(--color-danger)]",
            // Left padding when icon present
            hasLeftIcon && "ps-10",
            // Right padding when right control present
            hasRightControl && "pe-10",
            // Disabled
            disabled && "opacity-50 cursor-not-allowed"
          )}
          {...rest}
        />

        {/* Password toggle */}
        {isPassword && (
          <button
            type="button"
            onClick={() => setShowPassword((prev) => !prev)}
            disabled={disabled}
            aria-label={showPassword ? "Hide password" : "Show password"}
            className={cn(
              "absolute end-3 top-1/2 -translate-y-1/2 text-[var(--color-text-muted)] hover:text-[var(--color-text)] transition-colors",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)] rounded",
              disabled && "pointer-events-none opacity-50"
            )}
          >
            {showPassword ? <EyeOff size={16} aria-hidden="true" /> : <Eye size={16} aria-hidden="true" />}
          </button>
        )}

        {/* Search clear button */}
        {isSearch && clearable && value && (
          <button
            type="button"
            onClick={() => onChange?.({ target: { value: "" } })}
            disabled={disabled}
            aria-label="Clear search"
            className={cn(
              "absolute end-3 top-1/2 -translate-y-1/2 text-[var(--color-text-muted)] hover:text-[var(--color-text)] transition-colors",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)] rounded",
              disabled && "pointer-events-none opacity-50"
            )}
          >
            <X size={16} aria-hidden="true" />
          </button>
        )}
      </div>

      {error && (
        <p
          id={id ? `${id}-error` : undefined}
          role="alert"
          className="text-xs text-[var(--color-danger)] mt-1"
        >
          {error}
        </p>
      )}
    </div>
  );
}
