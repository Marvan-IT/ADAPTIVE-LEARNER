import {
  useState,
  useRef,
  useLayoutEffect,
  useCallback,
  useId,
} from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "framer-motion";
import { cn } from "./lib/utils";

const TOOLTIP_GAP = 8; // px between trigger and tooltip

function getInitialMotion(position) {
  switch (position) {
    case "bottom": return { opacity: 0, y: -4 };
    case "left":   return { opacity: 0, x: 4 };
    case "right":  return { opacity: 0, x: -4 };
    default:       return { opacity: 0, y: 4 }; // top
  }
}

// Arrow classes: a 6px border-triangle pointing toward the trigger
const arrowBase = "absolute w-0 h-0 border-[6px] border-transparent";

const arrowClasses = {
  top:    "border-t-[var(--color-text)] top-full left-1/2 -translate-x-1/2 border-b-0",
  bottom: "border-b-[var(--color-text)] bottom-full left-1/2 -translate-x-1/2 border-t-0",
  left:   "border-l-[var(--color-text)] left-full top-1/2 -translate-y-1/2 border-r-0",
  right:  "border-r-[var(--color-text)] right-full top-1/2 -translate-y-1/2 border-l-0",
};

/**
 * @param {React.ReactNode} props.content - Tooltip content
 * @param {"top"|"bottom"|"left"|"right"} [props.position="top"]
 * @param {number} [props.delay=300] - Show delay in ms
 * @param {React.ReactNode} props.children - Trigger element
 * @param {string} [props.className]
 */
export default function Tooltip({
  content,
  position = "top",
  delay = 300,
  children,
  className,
}) {
  const [visible, setVisible] = useState(false);
  const [coords, setCoords] = useState({ top: 0, left: 0 });
  const [actualPosition, setActualPosition] = useState(position);

  const triggerRef = useRef(null);
  const tooltipRef = useRef(null);
  const timerRef = useRef(null);
  const tooltipId = useId();

  // Compute tooltip position, flipping if it overflows the viewport
  const computePosition = useCallback(() => {
    if (!triggerRef.current) return;

    const trigger = triggerRef.current.getBoundingClientRect();
    const tooltipEl = tooltipRef.current;
    const tooltipW = tooltipEl ? tooltipEl.offsetWidth : 160;
    const tooltipH = tooltipEl ? tooltipEl.offsetHeight : 32;
    const vw = window.innerWidth;
    const vh = window.innerHeight;

    let resolved = position;

    // Determine if the preferred side has room; if not, flip
    if (position === "top"    && trigger.top    < tooltipH + TOOLTIP_GAP) resolved = "bottom";
    if (position === "bottom" && trigger.bottom > vh - tooltipH - TOOLTIP_GAP) resolved = "top";
    if (position === "left"   && trigger.left   < tooltipW + TOOLTIP_GAP) resolved = "right";
    if (position === "right"  && trigger.right  > vw - tooltipW - TOOLTIP_GAP) resolved = "left";

    let top = 0;
    let left = 0;

    switch (resolved) {
      case "top":
        top  = trigger.top - tooltipH - TOOLTIP_GAP + window.scrollY;
        left = trigger.left + trigger.width / 2 - tooltipW / 2 + window.scrollX;
        break;
      case "bottom":
        top  = trigger.bottom + TOOLTIP_GAP + window.scrollY;
        left = trigger.left + trigger.width / 2 - tooltipW / 2 + window.scrollX;
        break;
      case "left":
        top  = trigger.top + trigger.height / 2 - tooltipH / 2 + window.scrollY;
        left = trigger.left - tooltipW - TOOLTIP_GAP + window.scrollX;
        break;
      case "right":
        top  = trigger.top + trigger.height / 2 - tooltipH / 2 + window.scrollY;
        left = trigger.right + TOOLTIP_GAP + window.scrollX;
        break;
    }

    // Clamp horizontally so tooltip never overflows viewport
    left = Math.max(8, Math.min(left, vw - tooltipW - 8 + window.scrollX));

    setActualPosition(resolved);
    setCoords({ top, left });
  }, [position]);

  useLayoutEffect(() => {
    if (visible) computePosition();
  }, [visible, computePosition]);

  function handleMouseEnter() {
    timerRef.current = setTimeout(() => setVisible(true), delay);
  }

  function handleMouseLeave() {
    clearTimeout(timerRef.current);
    setVisible(false);
  }

  const initial = getInitialMotion(actualPosition);

  return (
    <>
      <span
        ref={triggerRef}
        className="relative inline-flex"
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
        aria-describedby={visible ? tooltipId : undefined}
      >
        {children}
      </span>

      {createPortal(
        <AnimatePresence>
          {visible && (
            <motion.div
              ref={tooltipRef}
              id={tooltipId}
              role="tooltip"
              initial={initial}
              animate={{ opacity: 1, y: 0, x: 0 }}
              exit={initial}
              transition={{ duration: 0.15 }}
              className={cn(
                "fixed z-[9999] pointer-events-none",
                "bg-[var(--color-text)] text-[var(--text-inverse)] text-xs px-2.5 py-1.5",
                "rounded-xl font-medium max-w-[200px] text-center",
                className
              )}
              style={{ top: coords.top, left: coords.left }}
            >
              {content}
              {/* Arrow pointing toward trigger */}
              <span className={cn(arrowBase, arrowClasses[actualPosition])} />
            </motion.div>
          )}
        </AnimatePresence>,
        document.body
      )}
    </>
  );
}
