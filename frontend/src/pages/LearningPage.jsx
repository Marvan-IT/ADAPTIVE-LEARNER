import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams, useNavigate, useSearchParams } from "react-router-dom";
import { useSession } from "../context/SessionContext";
import { useTheme } from "../context/ThemeContext";
import ProgressBar from "../components/learning/ProgressBar";
import CardLearningView from "../components/learning/CardLearningView";
import SocraticChat from "../components/learning/SocraticChat";
import CompletionView from "../components/learning/CompletionView";
import { trackEvent } from "../utils/analytics";
import { Loader, AlertCircle, LogOut } from "lucide-react";

export default function LearningPage() {
  const { t } = useTranslation();
  const { conceptId } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const {
    phase, startLesson, error, reset,
    session, conceptTitle, currentCardIndex,
    cards, cardAnswers, messages,
  } = useSession();
  const { setStyle } = useTheme();

  useEffect(() => {
    if (conceptId && phase === "IDLE") {
      const lessonStyle = searchParams.get("style");
      const interestsParam = searchParams.get("interests");
      const lessonInterests = interestsParam ? interestsParam.split(",").map(s => s.trim()).filter(Boolean) : [];
      if (lessonStyle) setStyle(lessonStyle);
      startLesson(decodeURIComponent(conceptId), lessonStyle, lessonInterests);
    }
  }, [conceptId, phase, startLesson]);

  useEffect(() => {
    return () => reset();
  }, [reset]);

  const [showExitConfirm, setShowExitConfirm] = useState(false);

  const handleExitConfirm = () => {
    trackEvent("lesson_exited", {
      concept_id: session?.concept_id,
      concept_title: conceptTitle,
      phase,
      card_index: currentCardIndex,
      cards_total: cards?.length || 0,
      questions_answered: Object.keys(cardAnswers).length,
      questions_correct: Object.values(cardAnswers).filter((a) => a.correct).length,
      chat_exchanges: messages?.length || 0,
    });
    reset();
    navigate("/map");
  };

  if (error) {
    return (
      <div style={{
        display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
        minHeight: "calc(100vh - 64px)", gap: "1rem", padding: "2rem",
      }}>
        <AlertCircle size={48} color="var(--color-danger)" />
        <h2 style={{ color: "var(--color-danger)", fontWeight: 700 }}>{t("common.error")}</h2>
        <p style={{ color: "var(--color-text-muted)", textAlign: "center", maxWidth: "400px" }}>
          {error}
        </p>
        <button
          onClick={() => { reset(); navigate("/map"); }}
          style={{
            padding: "0.6rem 1.5rem", borderRadius: "10px", border: "none",
            backgroundColor: "var(--color-primary)", color: "#fff",
            fontSize: "1rem", fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
          }}
        >
          {t("learning.backToMap")}
        </button>
      </div>
    );
  }

  if (phase === "LOADING" || phase === "IDLE") {
    return (
      <div style={{
        display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
        minHeight: "calc(100vh - 64px)", gap: "1rem",
      }}>
        <Loader size={40} color="var(--color-primary)" style={{ animation: "spin 1s linear infinite" }} />
        <p style={{ color: "var(--color-text-muted)", fontSize: "1.1rem" }}>
          {t("learning.craftingCards")}
        </p>
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      </div>
    );
  }

  return (
    <div style={{
      maxWidth: phase === "CARDS" ? "1100px" : "800px",
      margin: "0 auto",
      padding: "1.5rem 1.5rem 3rem",
    }}>
      {/* ── Exit bar (CARDS + CHECKING only) ── */}
      {(phase === "CARDS" || phase === "CHECKING") && (
        <div style={{
          display: "flex", justifyContent: "flex-end", alignItems: "center",
          marginBottom: "0.75rem", gap: "0.75rem",
        }}>
          {showExitConfirm ? (
            <div style={{
              display: "flex", alignItems: "center", gap: "0.75rem",
              padding: "0.5rem 1rem", borderRadius: "10px",
              backgroundColor: "var(--color-surface)",
              border: "2px solid var(--color-danger)",
            }}>
              <span style={{ fontSize: "0.9rem", color: "var(--color-text)", fontWeight: 600 }}>
                {t("learning.exitConfirm")}
              </span>
              <button
                onClick={handleExitConfirm}
                style={{
                  padding: "0.35rem 0.9rem", borderRadius: "8px", border: "none",
                  backgroundColor: "var(--color-danger)", color: "#fff",
                  fontSize: "0.85rem", fontWeight: 700,
                  cursor: "pointer", fontFamily: "inherit",
                }}
              >
                {t("learning.exitYes")}
              </button>
              <button
                onClick={() => setShowExitConfirm(false)}
                style={{
                  padding: "0.35rem 0.9rem", borderRadius: "8px",
                  border: "1px solid var(--color-border)",
                  backgroundColor: "transparent", color: "var(--color-text-muted)",
                  fontSize: "0.85rem", fontWeight: 600,
                  cursor: "pointer", fontFamily: "inherit",
                }}
              >
                {t("learning.exitNo")}
              </button>
            </div>
          ) : (
            <button
              onClick={() => setShowExitConfirm(true)}
              style={{
                display: "flex", alignItems: "center", gap: "0.35rem",
                padding: "0.4rem 0.9rem", borderRadius: "8px",
                border: "1px solid var(--color-border)",
                backgroundColor: "transparent", color: "var(--color-text-muted)",
                fontSize: "0.85rem", fontWeight: 600,
                cursor: "pointer", fontFamily: "inherit", transition: "all 0.15s",
              }}
            >
              <LogOut size={14} />
              {t("learning.exitLesson")}
            </button>
          )}
        </div>
      )}

      <ProgressBar phase={phase} />
      {phase === "CARDS" && <CardLearningView />}
      {phase === "CHECKING" && <SocraticChat />}
      {phase === "COMPLETED" && <CompletionView />}
    </div>
  );
}
