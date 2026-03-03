import { useEffect, useRef } from "react";

export default function ProgressRing({ score = 0, size = 130, strokeWidth = 8, color }) {
  const circleRef = useRef(null);
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;

  // Determine color from score bands (60% threshold)
  const ringColor = color || (
    score >= 90 ? "var(--score-excellent)" :
    score >= 60 ? "var(--score-pass)" :
    score >= 40 ? "var(--score-borderline)" :
    "var(--score-fail)"
  );

  useEffect(() => {
    if (!circleRef.current) return;
    // Animate from 0 to score% on mount
    const offset = circumference - (score / 100) * circumference;
    circleRef.current.style.strokeDashoffset = circumference; // start at 0%
    // Trigger animation on next frame
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        if (circleRef.current) {
          circleRef.current.style.transition = "stroke-dashoffset 0.8s ease-out";
          circleRef.current.style.strokeDashoffset = offset;
        }
      });
    });
  }, [score, circumference]);

  return (
    <svg width={size} height={size} style={{ display: "block" }} aria-hidden="true">
      {/* Track */}
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke="var(--color-border)"
        strokeWidth={strokeWidth}
      />
      {/* Progress arc */}
      <circle
        ref={circleRef}
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke={ringColor}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={circumference}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
        style={{ transition: "stroke-dashoffset 0.8s ease-out" }}
      />
    </svg>
  );
}
