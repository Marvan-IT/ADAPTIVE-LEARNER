import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useSession } from "../../context/SessionContext";
import { useStudent } from "../../context/StudentContext";
import { getNextConcepts } from "../../api/concepts";
import { formatConceptTitle } from "../../utils/formatConceptTitle";
import { useTranslation } from "react-i18next";
import { trackEvent } from "../../utils/analytics";
import { Trophy, Star, RefreshCw, Map, ArrowRight } from "lucide-react";

export default function CompletionView() {
  const { t } = useTranslation();
  const { score, mastered, conceptTitle, session, reset } = useSession();
  const { masteredConcepts } = useStudent();
  const navigate = useNavigate();
  const [nextConcept, setNextConcept] = useState(null);

  // Track completion_viewed once
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
        if (ready.length > 0) {
          setNextConcept(ready[0]);
        }
      })
      .catch(() => {});
  }, [masteredConcepts]);

  const scoreColor =
    score >= 90 ? "var(--color-success)" :
    score >= 70 ? "var(--color-primary)" :
    score >= 50 ? "#f59e0b" : "var(--color-danger)";

  return (
    <div style={{
      backgroundColor: "var(--color-surface)",
      borderRadius: "16px",
      border: "2px solid var(--color-border)",
      overflow: "hidden",
    }}>
      {/* Banner */}
      <div style={{
        background: mastered
          ? "linear-gradient(135deg, #22c55e, #16a34a)"
          : "linear-gradient(135deg, #f59e0b, #d97706)",
        padding: "1.5rem 2rem",
        textAlign: "center",
        color: "#fff",
      }}>
        {mastered ? (
          <>
            <Trophy size={40} style={{ marginBottom: "0.5rem" }} />
            <h2 style={{ fontSize: "1.5rem", fontWeight: 800, margin: "0 0 0.25rem" }}>
              {t("completion.mastered")}
            </h2>
            <p style={{ fontSize: "0.95rem", opacity: 0.9 }}>
              {t("completion.masteredMsg", { title: conceptTitle })}
            </p>
          </>
        ) : (
          <>
            <Star size={40} style={{ marginBottom: "0.5rem" }} />
            <h2 style={{ fontSize: "1.5rem", fontWeight: 800, margin: "0 0 0.25rem" }}>
              {t("completion.almostThere")}
            </h2>
            <p style={{ fontSize: "0.95rem", opacity: 0.9 }}>
              {t("completion.almostMsg", { title: conceptTitle })}
            </p>
          </>
        )}
      </div>

      {/* Score + Actions */}
      <div style={{ padding: "2rem", textAlign: "center" }}>
        {/* Score circle */}
        <div style={{
          width: "130px", height: "130px", borderRadius: "50%",
          border: `5px solid ${scoreColor}`,
          display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
          margin: "0 auto 1.5rem",
          backgroundColor: "var(--color-bg)",
        }}>
          <span style={{ fontSize: "2.2rem", fontWeight: 800, color: scoreColor }}>
            {score}
          </span>
          <span style={{ fontSize: "0.75rem", color: "var(--color-text-muted)", fontWeight: 600 }}>
            {t("completion.outOf")}
          </span>
        </div>

        {/* Actions */}
        <div style={{ display: "flex", flexDirection: "column", gap: "0.65rem", maxWidth: "300px", margin: "0 auto" }}>
          {!mastered && (
            <button
              onClick={() => {
                trackEvent("completion_action", { action: "try_again", concept_id: session?.concept_id, concept_title: conceptTitle });
                reset();
                window.location.reload();
              }}
              style={{
                display: "flex", alignItems: "center", justifyContent: "center", gap: "0.5rem",
                width: "100%", padding: "0.75rem",
                borderRadius: "12px", border: "none",
                backgroundColor: "var(--color-primary)", color: "#fff",
                fontSize: "1rem", fontWeight: 700,
                cursor: "pointer", fontFamily: "inherit",
              }}
            >
              <RefreshCw size={18} /> {t("completion.tryAgain")}
            </button>
          )}

          {mastered && nextConcept && (
            <button
              onClick={() => {
                trackEvent("completion_action", { action: "next_concept", concept_id: session?.concept_id, concept_title: conceptTitle, next_concept_id: nextConcept.concept_id, next_concept_title: nextConcept.concept_title || formatConceptTitle(nextConcept.concept_id) });
                reset();
                navigate(`/learn/${encodeURIComponent(nextConcept.concept_id)}`);
              }}
              style={{
                display: "flex", alignItems: "center", justifyContent: "center", gap: "0.5rem",
                width: "100%", padding: "0.75rem",
                borderRadius: "12px", border: "none",
                backgroundColor: "var(--color-primary)", color: "#fff",
                fontSize: "1rem", fontWeight: 700,
                cursor: "pointer", fontFamily: "inherit",
              }}
            >
              <ArrowRight size={18} />
              {t("completion.next", { title: nextConcept.concept_title || formatConceptTitle(nextConcept.concept_id) })}
            </button>
          )}

          <button
            onClick={() => { trackEvent("completion_action", { action: "back_to_map", concept_id: session?.concept_id, concept_title: conceptTitle }); reset(); navigate("/map"); }}
            style={{
              display: "flex", alignItems: "center", justifyContent: "center", gap: "0.5rem",
              width: "100%", padding: "0.65rem",
              borderRadius: "12px", border: "1.5px solid var(--color-border)",
              backgroundColor: "transparent", color: "var(--color-text-muted)",
              fontSize: "0.9rem", fontWeight: 600,
              cursor: "pointer", fontFamily: "inherit",
            }}
          >
            <Map size={16} /> {t("learning.backToMap")}
          </button>
        </div>
      </div>
    </div>
  );
}
