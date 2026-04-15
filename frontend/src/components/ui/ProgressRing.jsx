import { useEffect } from "react";
import { motion, useMotionValue, useSpring } from "framer-motion";
import { cn } from "./lib/utils";

/** @type {Record<string, { svgSize: number, strokeWidth: number }>} */
const SIZE_MAP = {
  sm: { svgSize: 64,  strokeWidth: 4  },
  md: { svgSize: 130, strokeWidth: 8  },
  lg: { svgSize: 180, strokeWidth: 10 },
};

/**
 * Circular progress ring with animated fill.
 * SVG-specific numeric attributes (strokeDasharray, strokeDashoffset) keep
 * inline style only on the circle element — all layout/positioning uses Tailwind.
 *
 * @param {{
 *   score: number,
 *   size?: "sm" | "md" | "lg",
 *   color?: string,
 *   label?: import("react").ReactNode,
 *   className?: string
 * }} props
 * @param {number}            props.score      - 0–100
 * @param {"sm"|"md"|"lg"}   [props.size="md"] - Preset size
 * @param {string}            [props.color]    - CSS color override; if omitted, score bands apply
 * @param {import("react").ReactNode} [props.label] - Content centered inside the ring
 * @param {string}            [props.className]
 */
export default function ProgressRing({ score = 0, size = "md", color, label, className }) {
  const { svgSize, strokeWidth } = SIZE_MAP[size] ?? SIZE_MAP.md;

  const radius = (svgSize - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;

  // Derive color from score band if no override provided
  const ringColor = color ?? (
    score >= 90 ? "var(--score-excellent)"  :
    score >= 60 ? "var(--score-pass)"       :
    score >= 40 ? "var(--score-borderline)" :
                  "var(--score-fail)"
  );

  // Spring-animated strokeDashoffset
  const targetOffset = circumference - (score / 100) * circumference;
  const motionOffset = useMotionValue(circumference);
  const springOffset = useSpring(motionOffset, { stiffness: 80, damping: 20 });

  useEffect(() => {
    motionOffset.set(targetOffset);
  }, [targetOffset, motionOffset]);

  return (
    <div className={cn("relative inline-flex items-center justify-center", className)}>
      <svg
        width={svgSize}
        height={svgSize}
        className="block"
        aria-hidden="true"
      >
        {/* Track */}
        <circle
          cx={svgSize / 2}
          cy={svgSize / 2}
          r={radius}
          fill="none"
          stroke="var(--color-border)"
          strokeWidth={strokeWidth}
        />
        {/* Progress arc — SVG math attributes must stay inline */}
        <motion.circle
          cx={svgSize / 2}
          cy={svgSize / 2}
          r={radius}
          fill="none"
          stroke={ringColor}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          style={{
            strokeDasharray: circumference,
            strokeDashoffset: springOffset,
            transform: `rotate(-90deg)`,
            transformOrigin: "50% 50%",
          }}
        />
      </svg>

      {/* Center label */}
      <div className="absolute inset-0 flex items-center justify-center">
        {label ?? (
          <span className="font-bold text-[var(--color-text)] leading-none text-sm">
            {score}%
          </span>
        )}
      </div>
    </div>
  );
}
