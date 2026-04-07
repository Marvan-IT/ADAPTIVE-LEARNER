import React from "react";
import { useTranslation } from "react-i18next";

/**
 * SubsectionNav — sidebar list of teaching subsections.
 *
 * Props:
 *   chunkList      — ChunkSummary[] from backend (all chunks for current section)
 *   chunkProgress  — { chunk_id: { score, mode_used } } from SessionContext
 *   currentChunkId — UUID string of the chunk currently being studied
 *   currentMode    — "STRUGGLING" | "NORMAL" | "FAST"
 */
export default function SubsectionNav({
  chunkList = [],
  chunkProgress = {},
  currentChunkId,
  currentMode = "NORMAL",
  onExitSubsection = null,
}) {
  const { t } = useTranslation();

  // Hide exam_question_source chunks (internal only)
  const visibleChunks = chunkList.filter(
    (c) => c.chunk_type !== "exam_question_source" && c.chunk_type !== "exercise_gate"
  );

  const modeColors = {
    STRUGGLING: { bg: "rgba(244,63,94,0.12)", text: "var(--color-danger)", label: t("subsectionNav.modeSlow", "Slow") },
    NORMAL: { bg: "rgba(99,102,241,0.12)", text: "var(--color-primary)", label: t("subsectionNav.modeNormal", "Normal") },
    FAST: { bg: "rgba(34,197,94,0.12)", text: "var(--color-success)", label: t("subsectionNav.modeFast", "Fast") },
  };

  return (
    <div style={{
      width: "220px",
      minWidth: "220px",
      background: "var(--color-surface)",
      borderRight: "1px solid var(--color-border)",
      padding: "12px 0",
      overflowY: "auto",
      flexShrink: 0,
    }}>
      {onExitSubsection && (
        <button
          onClick={onExitSubsection}
          style={{
            display: "flex",
            alignItems: "center",
            gap: "4px",
            background: "none",
            border: "none",
            cursor: "pointer",
            color: "var(--color-text-muted)",
            fontSize: "12px",
            padding: "6px 12px 4px",
            width: "100%",
            textAlign: "left",
            fontFamily: "inherit",
          }}
        >
          ← {t("learning.exitSubsection", "Back to list")}
        </button>
      )}
      <div style={{
        padding: "0 12px 8px",
        fontSize: "11px",
        fontWeight: 600,
        color: "var(--color-text-muted)",
        textTransform: "uppercase",
        letterSpacing: "0.05em",
      }}>
        {t("subsectionNav.title", "Subsections")}
      </div>

      {visibleChunks.map((chunk, idx) => {
        const isCurrent = chunk.chunk_id === currentChunkId;
        const isDone = chunk.chunk_id in chunkProgress;
        const score = chunkProgress[chunk.chunk_id]?.score;
        const isOptional = chunk.chunk_type === "practice";
        const isLocked = idx > 0
          && !(visibleChunks[idx - 1]?.chunk_id in (chunkProgress || {}));

        return (
          <div
            key={chunk.chunk_id}
            style={{
              padding: "8px 12px",
              margin: "2px 8px",
              borderRadius: "6px",
              background: isCurrent ? "rgba(99,102,241,0.12)" : "transparent",
              border: isCurrent ? "1.5px solid var(--color-primary)" : "1px solid transparent",
              cursor: isLocked ? "not-allowed" : "default",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
              {/* Status icon */}
              <span
                style={{ fontSize: "13px", flexShrink: 0, color: isDone ? "var(--color-success)" : isCurrent ? "var(--color-primary)" : "var(--color-text-muted)" }}
                aria-hidden="true"
              >
                {isDone ? "✓" : isLocked ? "🔒" : isCurrent ? "●" : "○"}
              </span>

              {/* Heading */}
              <span style={{
                fontSize: "12px",
                color: isDone ? "var(--color-success)" : isCurrent ? "var(--color-primary)" : "var(--color-text-muted)",
                fontWeight: isCurrent ? 600 : 400,
                lineHeight: "1.4",
                flex: 1,
              }}>
                {chunk.heading}
              </span>
            </div>

            {/* Score + mode badge row */}
            <div style={{ display: "flex", alignItems: "center", gap: "4px", marginTop: "3px", paddingLeft: "19px" }}>
              {isDone && score != null && (
                <span style={{
                  fontSize: "10px",
                  color: score >= 80 ? "var(--color-success)" : score >= 50 ? "var(--color-primary)" : "var(--color-danger)",
                  fontWeight: 600,
                }}>
                  {score}%
                </span>
              )}
              {isCurrent && (
                <span style={{
                  fontSize: "10px",
                  padding: "1px 5px",
                  borderRadius: "4px",
                  background: modeColors[currentMode]?.bg || "#dbeafe",
                  color: modeColors[currentMode]?.text || "#1e40af",
                  fontWeight: 600,
                }}>
                  {modeColors[currentMode]?.label || currentMode}
                </span>
              )}
              {isOptional && (
                <span style={{
                  fontSize: "10px",
                  color: "var(--color-warning)",
                  background: "rgba(245,158,11,0.12)",
                  padding: "1px 5px",
                  borderRadius: "4px",
                }}>
                  {t("subsectionNav.optional", "Optional")}
                </span>
              )}
              {isLocked && (
                <span style={{
                  fontSize: "10px",
                  color: "var(--color-text-muted)",
                  background: "rgba(148,163,184,0.12)",
                  padding: "1px 5px",
                  borderRadius: "4px",
                }}>
                  {t("subsectionNav.lockedSubsection", "Complete previous section first")}
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
