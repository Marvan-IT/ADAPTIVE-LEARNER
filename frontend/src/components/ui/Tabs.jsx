import {
  createContext,
  useContext,
  useId,
  useRef,
} from "react";
import { motion, AnimatePresence } from "framer-motion";
import { cn } from "./lib/utils";

// ── Context ───────────────────────────────────────────────────────────────────
const TabsContext = createContext({
  value: "",
  onValueChange: () => {},
  scopeId: "",
});

// ── Tabs ──────────────────────────────────────────────────────────────────────
/**
 * @param {string}          props.value           - Active tab key
 * @param {function}        props.onValueChange   - Called with the new tab key
 * @param {React.ReactNode} props.children
 * @param {string}          [props.className]
 */
export function Tabs({ value, onValueChange, children, className }) {
  const scopeId = useId().replace(/:/g, "");

  return (
    <TabsContext.Provider value={{ value, onValueChange, scopeId }}>
      <div className={cn("w-full", className)}>{children}</div>
    </TabsContext.Provider>
  );
}

// ── TabsList ──────────────────────────────────────────────────────────────────
/**
 * @param {React.ReactNode} props.children - Must be TabsTrigger elements
 * @param {string}          [props.className]
 */
export function TabsList({ children, className }) {
  const listRef = useRef(null);

  function handleKeyDown(e) {
    if (!listRef.current) return;
    const triggers = Array.from(
      listRef.current.querySelectorAll('[role="tab"]:not([disabled])')
    );
    const idx = triggers.indexOf(document.activeElement);
    if (idx === -1) return;

    if (e.key === "ArrowRight") {
      e.preventDefault();
      triggers[(idx + 1) % triggers.length].focus();
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      triggers[(idx - 1 + triggers.length) % triggers.length].focus();
    }
  }

  return (
    <div
      ref={listRef}
      role="tablist"
      onKeyDown={handleKeyDown}
      className={cn("flex gap-0 border-b border-[var(--color-border)]", className)}
    >
      {children}
    </div>
  );
}

// ── TabsTrigger ───────────────────────────────────────────────────────────────
/**
 * @param {string}          props.value     - Tab key this trigger controls
 * @param {React.ReactNode} props.children
 * @param {React.ReactNode} [props.icon]    - Optional Lucide icon rendered before label
 * @param {string}          [props.className]
 */
export function TabsTrigger({ value, children, icon, className }) {
  const { value: activeValue, onValueChange, scopeId } = useContext(TabsContext);
  const isActive = value === activeValue;
  const triggerId = `${scopeId}-trigger-${value}`;
  const panelId = `${scopeId}-panel-${value}`;

  return (
    <button
      id={triggerId}
      role="tab"
      aria-selected={isActive}
      aria-controls={panelId}
      tabIndex={isActive ? 0 : -1}
      onClick={() => onValueChange(value)}
      className={cn(
        "relative px-4 pb-3 pt-1 text-sm font-semibold transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)] focus-visible:ring-offset-2 rounded-t",
        isActive
          ? "text-[var(--color-primary)]"
          : "text-[var(--color-text-muted)] hover:text-[var(--color-text)]",
        icon && "inline-flex items-center gap-2",
        className
      )}
    >
      {icon && <span className="shrink-0" aria-hidden="true">{icon}</span>}
      {children}

      {isActive && (
        <motion.div
          layoutId={`${scopeId}-tab-underline`}
          className="absolute bottom-0 left-0 right-0 h-0.5 bg-[var(--color-primary)] rounded-full"
          transition={{ type: "spring", stiffness: 500, damping: 40 }}
        />
      )}
    </button>
  );
}

// ── TabsContent ───────────────────────────────────────────────────────────────
/**
 * @param {string}          props.value     - Tab key — content only renders when this matches Tabs value
 * @param {React.ReactNode} props.children
 * @param {string}          [props.className]
 */
export function TabsContent({ value, children, className }) {
  const { value: activeValue, scopeId } = useContext(TabsContext);
  const isActive = value === activeValue;
  const triggerId = `${scopeId}-trigger-${value}`;
  const panelId = `${scopeId}-panel-${value}`;

  return (
    <AnimatePresence mode="wait" initial={false}>
      {isActive && (
        <motion.div
          key={value}
          id={panelId}
          role="tabpanel"
          aria-labelledby={triggerId}
          tabIndex={0}
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -4 }}
          transition={{ duration: 0.15, ease: "easeOut" }}
          className={cn("pt-4 focus-visible:outline-none", className)}
        >
          {children}
        </motion.div>
      )}
    </AnimatePresence>
  );
}
