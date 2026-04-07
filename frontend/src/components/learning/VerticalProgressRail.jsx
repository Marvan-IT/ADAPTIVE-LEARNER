import { motion } from "framer-motion";

/**
 * VerticalProgressRail — shows card progress as vertical dots with connecting lines.
 * Props:
 *   total          — total number of cards
 *   current        — 0-based index of the active card
 *   cardStates     — { [cardIndex]: { mcqCorrect } } for coloring completed dots
 */
export default function VerticalProgressRail({ total = 0, current = 0, cardStates = {} }) {
  if (total === 0) return null;

  return (
    <div style={{
      width: "40px",
      minWidth: "40px",
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      paddingTop: "1.5rem",
      gap: 0,
      flexShrink: 0,
    }}>
      {Array.from({ length: total }).map((_, i) => {
        const isCompleted = i < current;
        const isCurrent = i === current;
        const wasCorrect = cardStates[i]?.mcqCorrect;

        let dotColor;
        if (isCompleted) {
          dotColor = wasCorrect === false ? "var(--color-danger)" : "var(--color-success)";
        } else if (isCurrent) {
          dotColor = "var(--color-primary)";
        } else {
          dotColor = "var(--color-border)";
        }

        return (
          <div key={i} style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
            {/* Dot */}
            <motion.div
              layout
              animate={isCurrent ? {
                scale: [1, 1.25, 1],
                boxShadow: [
                  `0 0 0 0 ${dotColor}`,
                  `0 0 0 4px rgba(99,102,241,0.25)`,
                  `0 0 0 0 rgba(99,102,241,0)`,
                ],
              } : { scale: 1, boxShadow: "none" }}
              transition={isCurrent ? { duration: 1.6, repeat: Infinity, ease: "easeInOut" } : { duration: 0.2 }}
              style={{
                width: isCurrent ? "12px" : "8px",
                height: isCurrent ? "12px" : "8px",
                borderRadius: "50%",
                backgroundColor: dotColor,
                flexShrink: 0,
                transition: "background-color 0.3s, width 0.2s, height 0.2s",
              }}
            />
            {/* Connector line (not after last dot) */}
            {i < total - 1 && (
              <div style={{
                width: "2px",
                height: "22px",
                backgroundColor: i < current ? "var(--color-success)" : "var(--color-border)",
                transition: "background-color 0.3s",
                flexShrink: 0,
              }} />
            )}
          </div>
        );
      })}
    </div>
  );
}
