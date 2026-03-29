import React from "react";
import { useTranslation } from "react-i18next";

/**
 * SubsectionNav — sidebar list of teaching subsections + EXAM button.
 *
 * Props:
 *   chunkList      — ChunkSummary[] from backend (all chunks for current section)
 *   chunkProgress  — { chunk_id: { score, mode_used } } from SessionContext
 *   currentChunkId — UUID string of the chunk currently being studied
 *   allStudyComplete — bool: true when exam button unlocks
 *   onExamClick    — callback for when student clicks EXAM button
 *   currentMode    — "STRUGGLING" | "NORMAL" | "FAST"
 */
export default function SubsectionNav({
  chunkList = [],
  chunkProgress = {},
  currentChunkId,
  allStudyComplete = false,
  onExamClick,
  currentMode = "NORMAL",
}) {
  const { t } = useTranslation();

  // Filter: only show teaching, practice, exercise_gate in nav
  // exam_question_source chunks are HIDDEN (used only for exam questions internally)
  const visibleChunks = chunkList.filter(
    (c) => c.chunk_type !== "exam_question_source"
  );

  const modeColors = {
    STRUGGLING: { bg: "#fef3c7", text: "#92400e", label: t("subsectionNav.modeSlow", "Slow") },
    NORMAL: { bg: "#dbeafe", text: "#1e40af", label: t("subsectionNav.modeNormal", "Normal") },
    FAST: { bg: "#dcfce7", text: "#166534", label: t("subsectionNav.modeFast", "Fast") },
  };

  return (
    <div style={{
      width: "220px",
      minWidth: "220px",
      background: "#f8fafc",
      borderRight: "1px solid #e2e8f0",
      padding: "12px 0",
      overflowY: "auto",
      flexShrink: 0,
    }}>
      <div style={{
        padding: "0 12px 8px",
        fontSize: "11px",
        fontWeight: 600,
        color: "#64748b",
        textTransform: "uppercase",
        letterSpacing: "0.05em",
      }}>
        {t("subsectionNav.title", "Subsections")}
      </div>

      {visibleChunks.map((chunk) => {
        if (chunk.chunk_type === "exercise_gate") {
          const locked = !allStudyComplete;
          return (
            <div
              key={chunk.chunk_id}
              onClick={locked ? undefined : onExamClick}
              role={locked ? undefined : "button"}
              tabIndex={locked ? undefined : 0}
              onKeyDown={locked ? undefined : (e) => {
                if (e.key === "Enter" || e.key === " ") onExamClick?.();
              }}
              aria-label={locked
                ? t("subsectionNav.locked", "Complete previous subsections first")
                : t("subsectionNav.exam", "Exam")}
              style={{
                margin: "8px 12px 0",
                padding: "10px 12px",
                borderRadius: "8px",
                background: locked ? "#f1f5f9" : "#7c3aed",
                color: locked ? "#94a3b8" : "#fff",
                cursor: locked ? "not-allowed" : "pointer",
                fontSize: "13px",
                fontWeight: 600,
                display: "flex",
                alignItems: "center",
                gap: "6px",
                border: locked ? "1px dashed #cbd5e1" : "none",
              }}
            >
              <span aria-hidden="true">📝</span>
              <span>{t("subsectionNav.exam", "Exam")}</span>
              {locked && (
                <span style={{ fontSize: "10px", marginLeft: "auto", color: "#94a3b8" }}>
                  {t("subsectionNav.lockedShort", "Locked")}
                </span>
              )}
            </div>
          );
        }

        const isCurrent = chunk.chunk_id === currentChunkId;
        const isDone = chunk.chunk_id in chunkProgress;
        const score = chunkProgress[chunk.chunk_id]?.score;
        const isOptional = chunk.chunk_type === "practice";

        return (
          <div
            key={chunk.chunk_id}
            style={{
              padding: "8px 12px",
              margin: "2px 8px",
              borderRadius: "6px",
              background: isCurrent ? "#ede9fe" : "transparent",
              border: isCurrent ? "1.5px solid #7c3aed" : "1px solid transparent",
              cursor: "default",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
              {/* Status icon */}
              <span
                style={{ fontSize: "13px", flexShrink: 0, color: isDone ? "#16a34a" : isCurrent ? "#5b21b6" : "#94a3b8" }}
                aria-hidden="true"
              >
                {isDone ? "✓" : isCurrent ? "●" : "○"}
              </span>

              {/* Heading */}
              <span style={{
                fontSize: "12px",
                color: isDone ? "#16a34a" : isCurrent ? "#5b21b6" : "#475569",
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
                  color: score >= 80 ? "#16a34a" : score >= 50 ? "#2563eb" : "#dc2626",
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
                  color: "#92400e",
                  background: "#fef3c7",
                  padding: "1px 5px",
                  borderRadius: "4px",
                }}>
                  {t("subsectionNav.optional", "Optional")}
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
