import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "framer-motion";
import { Search, X } from "lucide-react";
import { cn } from "./lib/utils";

/**
 * Command palette (Cmd+K / Ctrl+K) for quick navigation.
 * @param {Object} props
 * @param {{ id: string, label: string, icon?: import('react').ReactNode, category?: string, onSelect: Function }[]} props.commands
 * @param {string} [props.className]
 */
export default function CommandPalette({ commands = [], className }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [highlighted, setHighlighted] = useState(0);
  const inputRef = useRef(null);
  const listRef = useRef(null);

  // Global keyboard shortcut
  useEffect(() => {
    const handler = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  // Focus input on open
  useEffect(() => {
    if (open) {
      setQuery("");
      setHighlighted(0);
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  // Filter commands
  const filtered = useMemo(() => {
    if (!query.trim()) return commands;
    const q = query.toLowerCase();
    return commands.filter(
      (c) =>
        c.label.toLowerCase().includes(q) ||
        (c.category && c.category.toLowerCase().includes(q))
    );
  }, [commands, query]);

  // Group by category
  const grouped = useMemo(() => {
    const groups = {};
    filtered.forEach((cmd) => {
      const cat = cmd.category || "Actions";
      if (!groups[cat]) groups[cat] = [];
      groups[cat].push(cmd);
    });
    return groups;
  }, [filtered]);

  // Reset highlight when filter changes
  useEffect(() => {
    setHighlighted(0);
  }, [query]);

  const handleSelect = useCallback(
    (cmd) => {
      setOpen(false);
      cmd.onSelect();
    },
    []
  );

  const handleKeyDown = useCallback(
    (e) => {
      if (e.key === "Escape") {
        setOpen(false);
        return;
      }
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setHighlighted((h) => Math.min(h + 1, filtered.length - 1));
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setHighlighted((h) => Math.max(h - 1, 0));
      }
      if (e.key === "Enter" && filtered[highlighted]) {
        e.preventDefault();
        handleSelect(filtered[highlighted]);
      }
    },
    [filtered, highlighted, handleSelect]
  );

  // Scroll highlighted into view
  useEffect(() => {
    const el = listRef.current?.querySelector(`[data-index="${highlighted}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [highlighted]);

  if (!open) return null;

  let flatIndex = -1;

  return createPortal(
    <AnimatePresence>
      <motion.div
        className="fixed inset-0 z-50 flex items-start justify-center pt-[15vh]"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={() => setOpen(false)}
      >
        {/* Backdrop */}
        <div className="absolute inset-0 bg-[var(--overlay-bg)] backdrop-blur-sm" />

        {/* Panel */}
        <motion.div
          className={cn(
            "relative w-full max-w-lg bg-[var(--color-surface)] border border-[var(--color-border)] rounded-2xl shadow-[var(--shadow-xl)] overflow-hidden",
            className
          )}
          initial={{ opacity: 0, scale: 0.95, y: -8 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: -8 }}
          transition={{ duration: 0.15, ease: "easeOut" }}
          onClick={(e) => e.stopPropagation()}
          onKeyDown={handleKeyDown}
        >
          {/* Search input */}
          <div className="flex items-center gap-3 px-4 border-b border-[var(--color-border)]">
            <Search size={18} className="text-[var(--color-text-muted)] shrink-0" />
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search commands..."
              className="flex-1 h-12 bg-transparent text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] outline-none border-none"
            />
            {query && (
              <button
                type="button"
                onClick={() => setQuery("")}
                className="text-[var(--color-text-muted)] hover:text-[var(--color-text)] transition-colors"
                aria-label="Clear search"
              >
                <X size={16} />
              </button>
            )}
          </div>

          {/* Results */}
          <div ref={listRef} className="max-h-72 overflow-y-auto py-2" role="listbox">
            {filtered.length === 0 ? (
              <div className="px-4 py-8 text-center text-sm text-[var(--color-text-muted)]">
                No results found
              </div>
            ) : (
              Object.entries(grouped).map(([category, items]) => (
                <div key={category}>
                  <div className="px-4 py-1.5 text-[0.65rem] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
                    {category}
                  </div>
                  {items.map((cmd) => {
                    flatIndex++;
                    const idx = flatIndex;
                    return (
                      <div
                        key={cmd.id}
                        role="option"
                        aria-selected={highlighted === idx}
                        data-index={idx}
                        className={cn(
                          "flex items-center gap-3 px-4 py-2.5 text-sm cursor-pointer transition-colors",
                          highlighted === idx
                            ? "bg-[var(--color-primary-light)] text-[var(--color-text)]"
                            : "text-[var(--color-text)] hover:bg-[var(--color-surface-2)]"
                        )}
                        onClick={() => handleSelect(cmd)}
                        onMouseEnter={() => setHighlighted(idx)}
                      >
                        {cmd.icon && (
                          <span className="text-[var(--color-text-muted)] shrink-0">
                            {cmd.icon}
                          </span>
                        )}
                        <span className="flex-1 truncate">{cmd.label}</span>
                      </div>
                    );
                  })}
                </div>
              ))
            )}
          </div>

          {/* Footer hint */}
          <div className="flex items-center justify-between px-4 py-2 border-t border-[var(--color-border)] text-[0.65rem] text-[var(--color-text-muted)]">
            <span>Navigate with arrow keys</span>
            <span>
              <kbd className="px-1.5 py-0.5 rounded border border-[var(--color-border)] bg-[var(--color-surface-2)] font-mono text-[var(--color-text-muted)]">Esc</kbd> to close
            </span>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>,
    document.body
  );
}
