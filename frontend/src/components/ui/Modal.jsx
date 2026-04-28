import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useCallback,
} from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";
import { cn } from "./lib/utils";

// ── Context ─────────────────────────────────────────────────────────────────
const ModalContext = createContext({ onClose: null });

// ── Size map ────────────────────────────────────────────────────────────────
const sizeClasses = {
  sm: "max-w-sm",
  md: "max-w-lg",
  lg: "max-w-2xl",
};

// ── Focusable selector ───────────────────────────────────────────────────────
const FOCUSABLE =
  'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])';

// ── Modal ───────────────────────────────────────────────────────────────────
/**
 * @param {boolean}         props.open      - Controls visibility
 * @param {function}        props.onClose   - Called when backdrop or Escape pressed
 * @param {"sm"|"md"|"lg"}  [props.size="md"]
 * @param {React.ReactNode} props.children
 * @param {string}          [props.className] - Extra classes on the panel inner div
 */
export function Modal({ open, onClose, size = "md", children, className }) {
  const panelRef = useRef(null);
  const previousFocusRef = useRef(null);

  // ── Escape key ────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!open) return;
    function handleKey(e) {
      if (e.key === "Escape") onClose?.();
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [open, onClose]);

  // ── Scroll lock + focus management ───────────────────────────────────────
  useEffect(() => {
    if (!open) return;

    // Save previous overflow and lock body scroll
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    // Save element that had focus before opening
    previousFocusRef.current = document.activeElement;

    // Auto-focus first focusable element inside panel
    const frame = requestAnimationFrame(() => {
      if (!panelRef.current) return;
      const focusable = panelRef.current.querySelectorAll(FOCUSABLE);
      const first = focusable[0];
      if (first) first.focus();
    });

    return () => {
      cancelAnimationFrame(frame);
      document.body.style.overflow = previousOverflow;
      // Restore focus to the element that had it before the modal opened
      previousFocusRef.current?.focus?.();
    };
  }, [open]);

  // ── Focus trap ────────────────────────────────────────────────────────────
  const handlePanelKeyDown = useCallback((e) => {
    if (e.key !== "Tab" || !panelRef.current) return;

    const focusable = Array.from(panelRef.current.querySelectorAll(FOCUSABLE));
    if (focusable.length === 0) return;

    const first = focusable[0];
    const last = focusable[focusable.length - 1];

    if (e.shiftKey) {
      if (document.activeElement === first) {
        e.preventDefault();
        last.focus();
      }
    } else {
      if (document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  }, []);

  return createPortal(
    <ModalContext.Provider value={{ onClose }}>
      <AnimatePresence>
        {open && (
          <>
            {/* Backdrop */}
            <motion.div
              key="modal-backdrop"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}
              onClick={onClose}
              className="fixed inset-0 z-50 bg-[var(--overlay-bg)] backdrop-blur-[var(--overlay-blur)]"
              aria-hidden="true"
            />

            {/* Panel wrapper — centers content */}
            <motion.div
              key="modal-panel"
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              transition={{ duration: 0.15, ease: "easeOut" }}
              className="fixed inset-0 z-50 flex items-center justify-center p-4"
              onKeyDown={handlePanelKeyDown}
            >
              <div
                ref={panelRef}
                role="dialog"
                aria-modal="true"
                onClick={(e) => e.stopPropagation()}
                className={cn(
                  "bg-[var(--color-surface)] rounded-2xl shadow-[var(--shadow-xl)]",
                  "w-full overflow-hidden",
                  sizeClasses[size] ?? sizeClasses.md,
                  className
                )}
              >
                {children}
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </ModalContext.Provider>,
    document.body
  );
}

// ── ModalHeader ──────────────────────────────────────────────────────────────
/**
 * Reads onClose from ModalContext to auto-render the X dismiss button.
 * @param {React.ReactNode} props.children - Title content
 * @param {string}          [props.className]
 */
export function ModalHeader({ children, className }) {
  const { onClose } = useContext(ModalContext);

  return (
    <div
      className={cn(
        "flex items-center justify-between",
        "px-[var(--sp-6)] pt-[var(--sp-6)] pb-[var(--sp-4)]",
        className
      )}
    >
      <div className="text-base font-semibold text-[var(--color-text)] leading-snug">
        {children}
      </div>

      {onClose && (
        <button
          type="button"
          onClick={onClose}
          aria-label="Close dialog"
          className={cn(
            "ms-4 shrink-0 text-[var(--color-text-muted)] hover:text-[var(--color-text)]",
            "rounded-[var(--radius-sm)] transition-colors",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)]"
          )}
        >
          <X size={18} aria-hidden="true" />
        </button>
      )}
    </div>
  );
}

// ── ModalBody ────────────────────────────────────────────────────────────────
/**
 * @param {React.ReactNode} props.children
 * @param {string}          [props.className]
 */
export function ModalBody({ children, className }) {
  return (
    <div
      className={cn(
        "px-[var(--sp-6)] py-[var(--sp-4)] overflow-y-auto max-h-[70vh]",
        className
      )}
    >
      {children}
    </div>
  );
}

// ── ModalFooter ──────────────────────────────────────────────────────────────
/**
 * @param {React.ReactNode} props.children
 * @param {string}          [props.className]
 */
export function ModalFooter({ children, className }) {
  return (
    <div
      className={cn(
        "flex justify-end gap-4",
        "px-[var(--sp-6)] py-[var(--sp-5)]",
        "border-t border-[var(--color-border)]",
        className
      )}
    >
      {children}
    </div>
  );
}
