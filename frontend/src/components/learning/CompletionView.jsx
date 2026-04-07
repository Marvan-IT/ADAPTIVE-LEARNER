import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useSession } from "../../context/SessionContext";
import { useStudent } from "../../context/StudentContext";
import { getNextConcepts } from "../../api/concepts";
import { formatConceptTitle } from "../../utils/formatConceptTitle";
import { useTranslation } from "react-i18next";
import { trackEvent } from "../../utils/analytics";
import { RefreshCw, Map, ArrowRight } from "lucide-react";
import { motion } from "framer-motion";
import ProgressRing from "../ui/ProgressRing";

const CONFETTI_COLORS = ["#6366f1", "#22c55e", "#8b5cf6", "#f59e0b", "#ef4444", "#06b6d4"];

function Confetti() {
  const pieces = Array.from({ length: 14 }, (_, i) => i);
  return (
    <div aria-hidden="true" style={{ position: "absolute", top: 0, left: 0, right: 0, pointerEvents: "none", overflow: "hidden", height: "100%" }}>
      {pieces.map((i) => (
        <motion.div
          key={i}
          initial={{ y: -10, opacity: 1, rotate: 0 }}
          animate={{ y: 200, opacity: 0, rotate: (i % 2 ? 1 : -1) * (180 + i * 30) }}
          transition={{ duration: 0.85 + (i % 5) * 0.2, delay: i * 0.04, ease: "easeIn" }}
          style={{
            position: "absolute",
            top: "-10px",
            left: `${(i / 14) * 100 + (i % 3) * 2}%`,
            width: "8px",
            height: "8px",
            borderRadius: i % 3 === 0 ? "50%" : "2px",
            backgroundColor: CONFETTI_COLORS[i % CONFETTI_COLORS.length],
          }}
        />
      ))}
    </div>
  );
}

export default function CompletionView() {
  const { t } = useTranslation();
  const { score, mastered, conceptTitle, session, dispatch } = useSession();
  const { masteredConcepts } = useStudent();
  const navigate = useNavigate();
  const [nextConcept, setNextConcept] = useState(null);

  const trackedRef = useRef(false);
  useEffect(() => {
    if (!trackedRef.current) {
      trackedRef.current = true;
      trackEvent("completion_viewed", { score, mastered, concept_id: session?.concept_id, concept_title: conceptTitle });
    }
  }, [score, mastered]);

  useEffect(() => {
    getNextConcepts(masteredConcepts)
      .then((res) => {
        const ready = res.data.ready_to_learn || [];
        if (ready.length > 0) setNextConcept(ready[0]);
      })
      .catch(() => {});
  }, [masteredConcepts]);

  const scoreLabel =
    score >= 90 ? t("completion.excellent") || "Excellent!" :
    score >= 60 ? t("completion.mastered") :
    score >= 40 ? t("completion.almostThere") :
    t("completion.keepPracticing") || "Keep practicing";

  const scoreColor =
    score >= 90 ? "var(--score-excellent)" :
    score >= 60 ? "var(--score-pass)" :
    score >= 40 ? "var(--score-borderline)" :
    "var(--score-fail)";

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.92, y: 16 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 320, damping: 28 }}
      style={{
        backgroundColor: "var(--color-surface)",
        borderRadius: "var(--radius-xl)",
        border: "2px solid var(--color-border)",
        overflow: "hidden",
        position: "relative",
        maxWidth: "480px",
        margin: "0 auto",
      }}
    >
      {mastered && <Confetti />}

      {/* Header gradient banner */}
      <div style={{
        background: mastered
          ? "linear-gradient(135deg, var(--color-success), #16a34a)"
          : "linear-gradient(135deg, #f59e0b, #d97706)",
        padding: "1.5rem 2rem 2.5rem",
        textAlign: "center",
        color: "#fff",
      }}>
        <div style={{ fontSize: "2rem", marginBottom: "0.25rem" }}>
          {mastered ? "🎉" : "📚"}
        </div>
        <h2 style={{ fontSize: "1.4rem", fontWeight: 800, margin: 0 }}>
          {mastered ? t("completion.mastered") : t("completion.almostThere")}
        </h2>
        <p style={{ fontSize: "0.9rem", opacity: 0.9, marginTop: "0.25rem" }}>
          {mastered
            ? t("completion.masteredMsg", { title: conceptTitle })
            : t("completion.almostMsg", { title: conceptTitle })}
        </p>
      </div>

      {/* Score + Actions */}
      <div style={{ padding: "2rem", textAlign: "center" }}>
        {/* ProgressRing centered */}
        <div style={{ position: "relative", display: "inline-flex", alignItems: "center", justifyContent: "center", marginBottom: "1.5rem", marginTop: "-2.5rem" }}>
          <div style={{ borderRadius: "50%", backgroundColor: "var(--color-surface)", padding: "4px", boxShadow: "var(--shadow-lg)" }}>
            <ProgressRing score={score} size={130} strokeWidth={9} />
          </div>
          <div style={{
            position: "absolute",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
          }}>
            <span style={{ fontSize: "2rem", fontWeight: 800, color: scoreColor, lineHeight: 1 }}>
              {score}
            </span>
            <span style={{ fontSize: "0.65rem", color: "var(--color-text-muted)", fontWeight: 700 }}>
              {t("completion.outOf")}
            </span>
          </div>
        </div>

        <p style={{ fontWeight: 700, color: scoreColor, marginBottom: "1.5rem", fontSize: "1rem" }}>
          {scoreLabel}
        </p>

        {/* Actions */}
        <div style={{ display: "flex", flexDirection: "column", gap: "0.65rem", maxWidth: "300px", margin: "0 auto" }}>
          {!mastered && (
            <motion.button
              whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.97 }}
              onClick={() => {
                trackEvent("completion_action", { action: "try_again", concept_id: session?.concept_id, concept_title: conceptTitle });
                dispatch({ type: "SESSION_COMPLETED" });
                window.location.reload();
              }}
              style={{
                display: "flex", alignItems: "center", justifyContent: "center", gap: "0.5rem",
                width: "100%", padding: "0.75rem",
                borderRadius: "var(--radius-md)", border: "none",
                backgroundColor: "var(--color-primary)", color: "#fff",
                fontSize: "1rem", fontWeight: 700,
                cursor: "pointer", fontFamily: "inherit",
                boxShadow: "var(--shadow-sm)",
              }}
            >
              <RefreshCw size={18} /> {t("completion.tryAgain")}
            </motion.button>
          )}

          {mastered && nextConcept && (
            <motion.button
              whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.97 }}
              onClick={() => {
                trackEvent("completion_action", { action: "next_concept", concept_id: session?.concept_id, concept_title: conceptTitle, next_concept_id: nextConcept.concept_id, next_concept_title: nextConcept.concept_title || formatConceptTitle(nextConcept.concept_id) });
                dispatch({ type: "SESSION_COMPLETED" });
                navigate(`/learn/${encodeURIComponent(nextConcept.concept_id)}`);
              }}
              style={{
                display: "flex", alignItems: "center", justifyContent: "center", gap: "0.5rem",
                width: "100%", padding: "0.75rem",
                borderRadius: "var(--radius-md)", border: "none",
                backgroundColor: "var(--color-primary)", color: "#fff",
                fontSize: "1rem", fontWeight: 700,
                cursor: "pointer", fontFamily: "inherit",
                boxShadow: "var(--shadow-sm)",
              }}
            >
              <ArrowRight size={18} />
              {t("completion.next", { title: nextConcept.concept_title || formatConceptTitle(nextConcept.concept_id) })}
            </motion.button>
          )}

          <motion.button
            whileHover={{ scale: 1.01 }} whileTap={{ scale: 0.97 }}
            onClick={() => {
              trackEvent("completion_action", { action: "back_to_map", concept_id: session?.concept_id, concept_title: conceptTitle });
              dispatch({ type: "SESSION_COMPLETED" });
              navigate("/map");
            }}
            style={{
              display: "flex", alignItems: "center", justifyContent: "center", gap: "0.5rem",
              width: "100%", padding: "0.65rem",
              borderRadius: "var(--radius-md)", border: "1.5px solid var(--color-border)",
              backgroundColor: "transparent", color: "var(--color-text-muted)",
              fontSize: "0.9rem", fontWeight: 600,
              cursor: "pointer", fontFamily: "inherit",
            }}
          >
            <Map size={16} /> {t("learning.backToMap")}
          </motion.button>
        </div>
      </div>
    </motion.div>
  );
}
