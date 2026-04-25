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

const CONFETTI_COLORS = ["#F97316", "#22c55e", "#EA580C", "#f59e0b", "#ef4444", "#06b6d4"];

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
    if (!session?.book_slug) return;
    getNextConcepts(masteredConcepts, session.book_slug)
      .then((res) => {
        const ready = res.data.ready_to_learn || [];
        if (ready.length > 0) setNextConcept(ready[0]);
      })
      .catch(() => {});
  }, [masteredConcepts, session?.book_slug]);

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
      className="bg-[var(--color-surface)] rounded-[var(--radius-xl)] border-2 border-[var(--color-border)] overflow-hidden relative max-w-[480px] mx-auto"
    >
      {mastered && <Confetti />}

      {/* Header gradient banner */}
      <div
        className="text-center text-white px-8 pt-6 pb-10"
        style={{
          background: mastered
            ? "linear-gradient(135deg, var(--color-success), #16a34a)"
            : "linear-gradient(135deg, #FB923C, #F97316)",
        }}
      >
        <div className="text-[2rem] mb-1">
          {mastered ? "🎉" : "📚"}
        </div>
        <h2 className="text-[1.4rem] font-extrabold m-0">
          {mastered ? t("completion.mastered") : t("completion.almostThere")}
        </h2>
        <p className="text-[0.9rem] opacity-90 mt-1">
          {mastered
            ? t("completion.masteredMsg", { title: conceptTitle })
            : t("completion.almostMsg", { title: conceptTitle })}
        </p>
      </div>

      {/* Score + Actions */}
      <div className="p-8 text-center">
        {/* ProgressRing centered */}
        <div className="relative inline-flex items-center justify-center mb-6 -mt-10">
          <div className="rounded-full bg-[var(--color-surface)] p-1 shadow-lg">
            <ProgressRing score={score} size={130} strokeWidth={9} />
          </div>
          <div className="absolute flex flex-col items-center justify-center">
            <span className="text-[2rem] font-extrabold leading-none" style={{ color: scoreColor }}>
              {score}
            </span>
            <span className="text-[0.65rem] text-[var(--color-text-muted)] font-bold">
              {t("completion.outOf")}
            </span>
          </div>
        </div>

        <p className="font-bold mb-6 text-base" style={{ color: scoreColor }}>
          {scoreLabel}
        </p>

        {/* Actions */}
        <div className="flex flex-col gap-2.5 max-w-[300px] mx-auto">
          {!mastered && (
            <motion.button
              whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.97 }}
              onClick={() => {
                trackEvent("completion_action", { action: "try_again", concept_id: session?.concept_id, concept_title: conceptTitle });
                dispatch({ type: "SESSION_COMPLETED" });
                window.location.reload();
              }}
              className="flex items-center justify-center gap-2 w-full py-3 rounded-[var(--radius-md)] border-none bg-[var(--color-primary-dark)] text-white text-base font-bold cursor-pointer font-[inherit] shadow-sm"
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
              className="flex items-center justify-center gap-2 w-full py-3 rounded-[var(--radius-md)] border-none bg-[var(--color-primary-dark)] text-white text-base font-bold cursor-pointer font-[inherit] shadow-sm"
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
            className="flex items-center justify-center gap-2 w-full py-2.5 rounded-[var(--radius-md)] border-[1.5px] border-[var(--color-border)] bg-transparent text-[var(--color-text-muted)] text-[0.9rem] font-semibold cursor-pointer font-[inherit]"
          >
            <Map size={16} /> {t("learning.backToMap")}
          </motion.button>
        </div>
      </div>
    </motion.div>
  );
}
