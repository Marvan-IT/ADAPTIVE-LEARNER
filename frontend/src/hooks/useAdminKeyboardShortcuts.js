import { useEffect, useRef } from "react";
import { useLocation } from "react-router-dom";

const ADMIN_ROUTE_PREFIX = "/admin";

// Selectors for elements where undo/redo shortcuts must be suppressed
const FOCUS_BLOCK_SELECTORS = ["input", "textarea", "select", "[contenteditable]"];

/**
 * Registers global keyboard shortcuts for undo/redo within admin routes.
 *
 * Ctrl+Z (Cmd+Z on Mac)                  → onUndo()
 * Ctrl+Shift+Z / Ctrl+Y (Cmd+Shift+Z)   → onRedo()
 *
 * Shortcuts are ignored when focus is inside a text-input element.
 * A 300ms debounce prevents accidental double-triggers on key repeat.
 *
 * @param {{ onUndo: function, onRedo: function, canUndo: boolean, canRedo: boolean }} options
 */
export function useAdminKeyboardShortcuts({ onUndo, onRedo, canUndo, canRedo }) {
  const location = useLocation();
  const debounceRef = useRef(null);

  // Keep latest callbacks in a ref so the stable listener closure doesn't go stale
  const onUndoRef = useRef(onUndo);
  const onRedoRef = useRef(onRedo);
  const canUndoRef = useRef(canUndo);
  const canRedoRef = useRef(canRedo);

  useEffect(() => { onUndoRef.current = onUndo; }, [onUndo]);
  useEffect(() => { onRedoRef.current = onRedo; }, [onRedo]);
  useEffect(() => { canUndoRef.current = canUndo; }, [canUndo]);
  useEffect(() => { canRedoRef.current = canRedo; }, [canRedo]);

  useEffect(() => {
    if (!location.pathname.startsWith(ADMIN_ROUTE_PREFIX)) return;

    const handleKeyDown = (e) => {
      // Suppress when focus is inside a text-editing context
      const active = document.activeElement;
      if (active) {
        const blocked = FOCUS_BLOCK_SELECTORS.some((sel) => {
          try {
            return active.matches(sel);
          } catch {
            return false;
          }
        });
        if (blocked) return;
      }

      const isMac = navigator.platform?.toLowerCase().includes("mac");
      const ctrl = isMac ? e.metaKey : e.ctrlKey;

      if (!ctrl) return;

      const isUndo = !e.shiftKey && e.key === "z";
      const isRedo =
        (e.shiftKey && e.key === "z") ||
        (!e.shiftKey && e.key === "y");

      if (!isUndo && !isRedo) return;

      e.preventDefault();

      // 300ms debounce — ignore rapid repeats (key held down or double-tap)
      if (debounceRef.current) return;
      debounceRef.current = setTimeout(() => {
        debounceRef.current = null;
      }, 300);

      if (isUndo && canUndoRef.current) onUndoRef.current?.();
      if (isRedo && canRedoRef.current) onRedoRef.current?.();
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
        debounceRef.current = null;
      }
    };
  }, [location.pathname]);
}
