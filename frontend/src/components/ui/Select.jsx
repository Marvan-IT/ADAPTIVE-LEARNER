import { useState, useRef, useEffect, useId } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ChevronDown, Check } from "lucide-react";
import { cn } from "./lib/utils";

/**
 * Accessible single-select dropdown built without a native <select>.
 *
 * @param {Array<{ value: string, label: string, icon?: React.ReactNode }>} props.options
 * @param {string}   props.value        - Currently selected value
 * @param {function} props.onChange     - Called with the new value string
 * @param {string}   [props.placeholder="Select..."]
 * @param {string}   [props.error]      - Error message shown below the trigger
 * @param {boolean}  [props.disabled]
 * @param {string}   [props.className]  - Extra classes on the outer wrapper div
 * @param {string}   [props.id]         - id forwarded to the combobox button
 */
export default function Select({
  options = [],
  value,
  onChange,
  placeholder = "Select...",
  error,
  disabled = false,
  className,
  id,
}) {
  const [isOpen, setIsOpen] = useState(false);
  const [highlightedIndex, setHighlightedIndex] = useState(-1);

  const containerRef = useRef(null);
  const listboxId = useId();

  const selectedOption = options.find((o) => o.value === value) ?? null;

  // ── Close on outside click ────────────────────────────────────────────────
  useEffect(() => {
    if (!isOpen) return;
    function handleOutsideClick(e) {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleOutsideClick);
    return () => document.removeEventListener("mousedown", handleOutsideClick);
  }, [isOpen]);

  // ── Reset highlight when closing ──────────────────────────────────────────
  useEffect(() => {
    if (!isOpen) setHighlightedIndex(-1);
  }, [isOpen]);

  // ── Keyboard handling on the trigger ─────────────────────────────────────
  function handleTriggerKeyDown(e) {
    switch (e.key) {
      case "Enter":
      case " ":
        e.preventDefault();
        if (!isOpen) {
          setIsOpen(true);
          // Highlight the currently selected item, or the first
          const idx = options.findIndex((o) => o.value === value);
          setHighlightedIndex(idx >= 0 ? idx : 0);
        } else {
          // Confirm highlighted option
          if (highlightedIndex >= 0) {
            selectOption(options[highlightedIndex]);
          }
        }
        break;

      case "ArrowDown":
        e.preventDefault();
        if (!isOpen) {
          setIsOpen(true);
          setHighlightedIndex(0);
        } else {
          setHighlightedIndex((prev) =>
            Math.min(prev + 1, options.length - 1)
          );
        }
        break;

      case "ArrowUp":
        e.preventDefault();
        if (isOpen) {
          setHighlightedIndex((prev) => Math.max(prev - 1, 0));
        }
        break;

      case "Escape":
        e.preventDefault();
        setIsOpen(false);
        break;

      case "Tab":
        // Let Tab close the dropdown naturally (focus leaves component)
        setIsOpen(false);
        break;

      default:
        break;
    }
  }

  function selectOption(option) {
    onChange?.(option.value);
    setIsOpen(false);
  }

  function toggleOpen() {
    if (disabled) return;
    setIsOpen((prev) => !prev);
    if (!isOpen) {
      const idx = options.findIndex((o) => o.value === value);
      setHighlightedIndex(idx >= 0 ? idx : 0);
    }
  }

  return (
    <div ref={containerRef} className={cn("relative flex flex-col", className)}>
      {/* Trigger */}
      <button
        id={id}
        type="button"
        role="combobox"
        aria-expanded={isOpen}
        aria-haspopup="listbox"
        aria-controls={isOpen ? listboxId : undefined}
        aria-invalid={error ? "true" : undefined}
        disabled={disabled}
        onClick={toggleOpen}
        onKeyDown={handleTriggerKeyDown}
        className={cn(
          // Base — mirrors Input component styling
          "w-full h-12 rounded-xl border-2 border-slate-200",
          "bg-[var(--input-bg)] text-[var(--color-text)]",
          "px-3 text-sm text-start",
          "flex items-center justify-between",
          "transition-colors",
          // Focus ring
          "focus:outline-none focus:ring-2 focus:ring-[var(--color-primary-light)] focus:border-[var(--color-primary)]",
          // Error state
          error &&
            "border-[var(--color-danger)] focus:ring-[var(--color-danger)] focus:border-[var(--color-danger)]",
          // Disabled state
          disabled && "opacity-50 cursor-not-allowed"
        )}
      >
        <span
          className={cn(
            "truncate",
            !selectedOption && "text-[var(--color-text-muted)]"
          )}
        >
          {selectedOption ? selectedOption.label : placeholder}
        </span>

        {/* Chevron — rotates when open */}
        <motion.span
          animate={{ rotate: isOpen ? 180 : 0 }}
          transition={{ duration: 0.15 }}
          className="ms-2 shrink-0 text-[var(--color-text-muted)]"
          aria-hidden="true"
        >
          <ChevronDown size={16} />
        </motion.span>
      </button>

      {/* Dropdown panel */}
      <AnimatePresence>
        {isOpen && (
          <motion.div
            key="select-dropdown"
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.12, ease: "easeOut" }}
            id={listboxId}
            role="listbox"
            aria-activedescendant={
              highlightedIndex >= 0
                ? `${listboxId}-option-${highlightedIndex}`
                : undefined
            }
            className={cn(
              "absolute top-full mt-1 w-full",
              "bg-[var(--color-surface)] border border-[var(--color-border)]",
              "rounded-xl shadow-[var(--shadow-lg)]",
              "z-50 overflow-hidden",
              "max-h-60 overflow-y-auto"
            )}
          >
            {options.length === 0 ? (
              <div className="px-3 py-2.5 text-sm text-[var(--color-text-muted)]">
                No options
              </div>
            ) : (
              options.map((option, index) => {
                const isSelected = option.value === value;
                const isHighlighted = index === highlightedIndex;

                return (
                  <div
                    key={option.value}
                    id={`${listboxId}-option-${index}`}
                    role="option"
                    aria-selected={isSelected}
                    onMouseDown={(e) => {
                      // Prevent blur on trigger before we handle the click
                      e.preventDefault();
                      selectOption(option);
                    }}
                    onMouseEnter={() => setHighlightedIndex(index)}
                    className={cn(
                      "px-3 py-2.5 text-sm cursor-pointer",
                      "flex items-center gap-2",
                      "transition-colors",
                      isHighlighted && "bg-[color-mix(in_srgb,var(--color-primary)_8%,transparent)]",
                      isSelected && "font-medium text-[var(--color-text)]",
                      !isSelected && "text-[var(--color-text)]"
                    )}
                  >
                    {/* Optional icon */}
                    {option.icon && (
                      <span className="shrink-0 text-[var(--color-text-muted)]" aria-hidden="true">
                        {option.icon}
                      </span>
                    )}

                    {/* Label */}
                    <span className="flex-1 truncate">{option.label}</span>

                    {/* Selected checkmark */}
                    {isSelected && (
                      <span
                        className="ms-auto shrink-0 text-[var(--color-primary)]"
                        aria-hidden="true"
                      >
                        <Check size={14} />
                      </span>
                    )}
                  </div>
                );
              })
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Error message */}
      {error && (
        <p role="alert" className="text-xs text-[var(--color-danger)] mt-1">
          {error}
        </p>
      )}
    </div>
  );
}
