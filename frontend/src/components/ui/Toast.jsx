import {
  createContext,
  useContext,
  useReducer,
  useCallback,
  useId,
} from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Info,
  X,
} from "lucide-react";
import { cn } from "./lib/utils";

// ── Context ──────────────────────────────────────────────────────────────────
const ToastContext = createContext({ toast: () => {} });

// ── Reducer ───────────────────────────────────────────────────────────────────
function toastReducer(state, action) {
  switch (action.type) {
    case "ADD":
      return [...state, action.toast];
    case "REMOVE":
      return state.filter((t) => t.id !== action.id);
    default:
      return state;
  }
}

// ── Variant config ────────────────────────────────────────────────────────────
const variantConfig = {
  success: {
    icon: CheckCircle2,
    borderClass: "border-s-[var(--color-success)]",
    iconClass: "text-[var(--color-success)]",
  },
  warning: {
    icon: AlertTriangle,
    borderClass: "border-s-[var(--color-warning)]",
    iconClass: "text-[var(--color-warning)]",
  },
  danger: {
    icon: XCircle,
    borderClass: "border-s-[var(--color-danger)]",
    iconClass: "text-[var(--color-danger)]",
  },
  info: {
    icon: Info,
    borderClass: "border-s-[var(--color-info)]",
    iconClass: "text-[var(--color-info)]",
  },
};

// ── ToastProvider ─────────────────────────────────────────────────────────────
/**
 * Wrap your app (or a subtree) with ToastProvider.
 * Access the toast() function via useToast().
 */
export function ToastProvider({ children }) {
  const [toasts, dispatch] = useReducer(toastReducer, []);

  const toast = useCallback(
    ({ variant = "info", title, description, duration = 4000 } = {}) => {
      // Unique id that doesn't rely on useId (called outside render)
      const id = `toast-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;

      dispatch({ type: "ADD", toast: { id, variant, title, description } });

      setTimeout(() => {
        dispatch({ type: "REMOVE", id });
      }, duration);
    },
    []
  );

  const dismiss = useCallback((id) => {
    dispatch({ type: "REMOVE", id });
  }, []);

  return (
    <ToastContext.Provider value={{ toast, toasts, dismiss }}>
      {children}
    </ToastContext.Provider>
  );
}

// ── useToast ──────────────────────────────────────────────────────────────────
/**
 * @returns {{ toast: function({ variant?, title, description?, duration? }): void }}
 */
export function useToast() {
  const { toast } = useContext(ToastContext);
  return { toast };
}

// ── Individual Toast item ─────────────────────────────────────────────────────
function ToastItem({ id, variant = "info", title, description }) {
  const { dismiss } = useContext(ToastContext);
  const config = variantConfig[variant] ?? variantConfig.info;
  const Icon = config.icon;

  return (
    <motion.div
      layout
      initial={{ opacity: 0, x: 100 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 100 }}
      transition={{ duration: 0.2, ease: "easeOut" }}
      role="status"
      aria-live="polite"
      className={cn(
        "pointer-events-auto",
        "flex items-start gap-3 w-80 p-4",
        "rounded-2xl",
        "bg-[var(--color-surface)] border border-[var(--color-border)] border-s-4",
        "shadow-[var(--shadow-lg)]",
        config.borderClass
      )}
    >
      {/* Variant icon */}
      <span className={cn("mt-0.5 shrink-0", config.iconClass)} aria-hidden="true">
        <Icon size={16} />
      </span>

      {/* Text content */}
      <div className="flex-1 min-w-0">
        {title && (
          <p className="text-sm font-semibold text-[var(--color-text)] leading-snug">
            {title}
          </p>
        )}
        {description && (
          <p className="text-xs text-[var(--color-text-muted)] mt-0.5 leading-snug">
            {description}
          </p>
        )}
      </div>

      {/* Dismiss button */}
      <button
        type="button"
        onClick={() => dismiss(id)}
        aria-label="Dismiss notification"
        className={cn(
          "shrink-0 mt-0.5 text-[var(--color-text-muted)] hover:text-[var(--color-text)]",
          "rounded transition-colors",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)]"
        )}
      >
        <X size={14} aria-hidden="true" />
      </button>
    </motion.div>
  );
}

// ── Toaster ───────────────────────────────────────────────────────────────────
/**
 * Place <Toaster /> once inside <ToastProvider>, anywhere in the tree.
 * It renders the live toast stack in the bottom-end corner.
 */
export function Toaster() {
  const { toasts } = useContext(ToastContext);

  return (
    <div
      aria-label="Notifications"
      className="fixed bottom-4 end-4 z-[var(--toast-z)] flex flex-col gap-2 pointer-events-none"
    >
      <AnimatePresence initial={false}>
        {toasts.map((t) => (
          <ToastItem key={t.id} {...t} />
        ))}
      </AnimatePresence>
    </div>
  );
}
