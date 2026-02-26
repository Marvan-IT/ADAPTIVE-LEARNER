import { X, Play, Lock, CheckCircle } from "lucide-react";
import { formatConceptTitle } from "../../utils/formatConceptTitle";
import { useTranslation } from "react-i18next";

export default function ConceptTooltip({ node, status, onClose, onLearn }) {
  const { t } = useTranslation();
  const title = node.title || formatConceptTitle(node.concept_id);

  return (
    <div style={{
      position: "absolute", top: "1rem", right: "1rem",
      width: "320px", maxHeight: "calc(100vh - 120px)",
      backgroundColor: "var(--color-surface)", borderRadius: "16px",
      border: "2px solid var(--color-border)",
      boxShadow: "0 8px 32px rgba(0,0,0,0.12)",
      padding: "1.5rem", overflow: "auto", zIndex: 10,
    }}>
      {/* Close button */}
      <button
        onClick={onClose}
        style={{
          position: "absolute", top: "0.75rem", right: "0.75rem",
          background: "none", border: "none", cursor: "pointer",
          color: "var(--color-text-muted)",
        }}
      >
        <X size={20} />
      </button>

      {/* Status badge */}
      <div style={{
        display: "inline-flex", alignItems: "center", gap: "0.3rem",
        padding: "0.25rem 0.7rem", borderRadius: "20px", marginBottom: "0.75rem",
        fontSize: "0.8rem", fontWeight: 700,
        backgroundColor:
          status === "mastered" ? "#dcfce7" :
          status === "ready" ? "#dbeafe" : "#f1f5f9",
        color:
          status === "mastered" ? "#16a34a" :
          status === "ready" ? "#2563eb" : "#64748b",
      }}>
        {status === "mastered" && <><CheckCircle size={14} /> {t("map.mastered")}</>}
        {status === "ready" && <><Play size={14} /> {t("map.readyToLearn")}</>}
        {status === "locked" && <><Lock size={14} /> {t("map.locked")}</>}
      </div>

      {/* Title */}
      <h3 style={{ fontSize: "1.2rem", fontWeight: 700, color: "var(--color-text)", marginBottom: "0.5rem" }}>
        {title}
      </h3>

      {/* Chapter/Section */}
      <p style={{ fontSize: "0.85rem", color: "var(--color-text-muted)", marginBottom: "1rem" }}>
        {t("map.chapterSection", { chapter: node.chapter, section: node.section })}
      </p>

      {/* Action */}
      {status === "ready" && (
        <button
          onClick={onLearn}
          style={{
            display: "flex", alignItems: "center", justifyContent: "center", gap: "0.5rem",
            width: "100%", padding: "0.7rem",
            borderRadius: "12px", border: "none",
            backgroundColor: "var(--color-primary)", color: "#fff",
            fontSize: "1rem", fontWeight: 700,
            cursor: "pointer", fontFamily: "inherit",
          }}
        >
          <Play size={18} /> {t("map.startLesson")}
        </button>
      )}

      {status === "mastered" && (
        <p style={{
          textAlign: "center", padding: "0.5rem",
          color: "var(--color-success)", fontWeight: 600,
        }}>
          {t("map.masteredMsg")}
        </p>
      )}

      {status === "locked" && (
        <p style={{
          textAlign: "center", padding: "0.5rem",
          color: "var(--color-text-muted)", fontSize: "0.9rem",
        }}>
          {t("map.lockedMsg")}
        </p>
      )}
    </div>
  );
}
