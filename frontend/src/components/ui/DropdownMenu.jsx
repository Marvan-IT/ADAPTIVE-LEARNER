import {
  createContext,
  useContext,
  useRef,
  useState,
  useEffect,
  useCallback,
} from "react";
import { AnimatePresence, motion } from "framer-motion";
import { cn } from "./lib/utils";

// ── Context ───────────────────────────────────────────────────────────────────
const DropdownContext = createContext({
  isOpen: false,
  setIsOpen: () => {},
  triggerRef: null,
  contentRef: null,
});

// ── DropdownMenu ──────────────────────────────────────────────────────────────
/**
 * @param {React.ReactNode} props.children
 */
export function DropdownMenu({ children }) {
  const [isOpen, setIsOpen] = useState(false);
  const triggerRef = useRef(null);
  const contentRef = useRef(null);

  // Close on outside click
  useEffect(() => {
    if (!isOpen) return;
    function handlePointerDown(e) {
      if (
        triggerRef.current?.contains(e.target) ||
        contentRef.current?.contains(e.target)
      ) {
        return;
      }
      setIsOpen(false);
    }
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [isOpen]);

  return (
    <DropdownContext.Provider value={{ isOpen, setIsOpen, triggerRef, contentRef }}>
      <div className="relative inline-block">{children}</div>
    </DropdownContext.Provider>
  );
}

// ── DropdownTrigger ───────────────────────────────────────────────────────────
/**
 * @param {React.ReactNode} props.children - The element that toggles the dropdown
 * @param {string}          [props.className]
 */
export function DropdownTrigger({ children, className }) {
  const { isOpen, setIsOpen, triggerRef } = useContext(DropdownContext);

  return (
    <div
      ref={triggerRef}
      onClick={() => setIsOpen((prev) => !prev)}
      aria-haspopup="menu"
      aria-expanded={isOpen}
      className={cn("inline-flex", className)}
    >
      {children}
    </div>
  );
}

// ── DropdownContent ───────────────────────────────────────────────────────────
/**
 * @param {React.ReactNode}      props.children
 * @param {"start"|"end"}        [props.align="end"]
 * @param {string}               [props.className]
 */
export function DropdownContent({ children, align = "end", className }) {
  const { isOpen, setIsOpen, contentRef } = useContext(DropdownContext);

  // Keyboard navigation: ArrowDown / ArrowUp / Escape
  const handleKeyDown = useCallback(
    (e) => {
      if (!contentRef.current) return;
      const items = Array.from(
        contentRef.current.querySelectorAll('[role="menuitem"]:not([aria-disabled="true"])')
      );

      if (e.key === "Escape") {
        e.preventDefault();
        setIsOpen(false);
        return;
      }

      if (e.key === "ArrowDown") {
        e.preventDefault();
        const idx = items.indexOf(document.activeElement);
        items[(idx + 1) % items.length]?.focus();
        return;
      }

      if (e.key === "ArrowUp") {
        e.preventDefault();
        const idx = items.indexOf(document.activeElement);
        items[(idx - 1 + items.length) % items.length]?.focus();
        return;
      }
    },
    [contentRef, setIsOpen]
  );

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          ref={contentRef}
          role="menu"
          initial={{ opacity: 0, scale: 0.95, y: -4 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: -4 }}
          transition={{ duration: 0.12, ease: "easeOut" }}
          onKeyDown={handleKeyDown}
          style={{
            position: "absolute",
            zIndex: 50,
            marginTop: "4px",
            minWidth: "180px",
            backgroundColor: "#FFFFFF",
            border: "1px solid #E2E8F0",
            borderRadius: "12px",
            boxShadow: "0 4px 16px rgba(0,0,0,0.12)",
            overflow: "hidden",
            padding: "4px 0",
            right: align === "end" ? 0 : undefined,
            left: align === "start" ? 0 : undefined,
          }}
          className={cn(
            className
          )}
        >
          {children}
        </motion.div>
      )}
    </AnimatePresence>
  );
}

// ── DropdownItem ──────────────────────────────────────────────────────────────
/**
 * @param {function}        [props.onSelect]
 * @param {React.ReactNode} [props.icon]
 * @param {boolean}         [props.destructive]
 * @param {boolean}         [props.disabled]
 * @param {React.ReactNode} props.children
 * @param {string}          [props.className]
 */
export function DropdownItem({
  onSelect,
  icon,
  destructive = false,
  disabled = false,
  children,
  className,
}) {
  const { setIsOpen } = useContext(DropdownContext);

  function handleClick() {
    if (disabled) return;
    onSelect?.();
    setIsOpen(false);
  }

  function handleKeyDown(e) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      handleClick();
    }
  }

  return (
    <div
      role="menuitem"
      tabIndex={disabled ? undefined : -1}
      aria-disabled={disabled ? "true" : undefined}
      onClick={handleClick}
      onKeyDown={handleKeyDown}
      className={cn(
        "px-3 py-2 text-sm cursor-pointer flex items-center gap-2 transition-colors",
        "text-[var(--color-text)]",
        destructive
          ? "text-[var(--color-danger)] hover:bg-[color-mix(in_srgb,var(--color-danger)_8%,transparent)]"
          : "hover:bg-[color-mix(in_srgb,var(--color-primary)_8%,transparent)]",
        disabled && "opacity-50 cursor-not-allowed pointer-events-none",
        className
      )}
    >
      {icon && (
        <span className="shrink-0 [&>svg]:size-4" aria-hidden="true">
          {icon}
        </span>
      )}
      {children}
    </div>
  );
}

// ── DropdownDivider ───────────────────────────────────────────────────────────
export function DropdownDivider() {
  return (
    <div
      role="separator"
      className="border-t border-[var(--color-border)] my-1"
    />
  );
}
