import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams, useNavigate, useSearchParams } from "react-router-dom";
import { useSession } from "../context/SessionContext";
import { useTheme } from "../context/ThemeContext";
import { useStudent } from "../context/StudentContext";
import ProgressBar from "../components/learning/ProgressBar";
import CardLearningView from "../components/learning/CardLearningView";
import SocraticChat from "../components/learning/SocraticChat";
import CompletionView from "../components/learning/CompletionView";
import { trackEvent } from "../utils/analytics";
import { AlertCircle, LogOut, MapPin } from "lucide-react";
import { checkConceptReadiness } from "../api/concepts";

export default function LearningPage() {
  const { t } = useTranslation();
  const { conceptId } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const {
    phase, startLesson, error, reset,
    session, conceptTitle, currentCardIndex,
    cards, cardAnswers, messages,
    checkScore, bestScore,
  } = useSession();
  const { setStyle } = useTheme();
  const { student } = useStudent();

  const [lessonInterests, setLessonInterests] = useState([]);
  const [interestInput, setInterestInput] = useState("");
  const [showCustomize, setShowCustomize] = useState(false);
  const [prereqWarning, setPrereqWarning] = useState(null); // null | { unmet: [...], style, interests }
  const [prereqChecked, setPrereqChecked] = useState(false);

  useEffect(() => {
    if (conceptId && phase === "IDLE" && !prereqChecked) {
      setPrereqChecked(true);
      const lessonStyle = searchParams.get("style");
      const interestsParam = searchParams.get("interests");
      const urlInterests = interestsParam ? interestsParam.split(",").map(s => s.trim()).filter(Boolean) : [];
      const mergedInterests = [...new Set([...urlInterests, ...lessonInterests])];
      if (lessonStyle) setStyle(lessonStyle);

      checkConceptReadiness(decodeURIComponent(conceptId), student.id)
        .then(res => {
          const data = res.data;
          if (!data.all_prerequisites_met && data.unmet_prerequisites.length > 0) {
            setPrereqWarning({ unmet: data.unmet_prerequisites, style: lessonStyle, interests: mergedInterests });
          } else {
            startLesson(decodeURIComponent(conceptId), lessonStyle, mergedInterests);
          }
        })
        .catch((err) => {
          console.error("[LearningPage] prereq check failed:", err);
          startLesson(decodeURIComponent(conceptId), lessonStyle, mergedInterests);
        });
    }
  }, [conceptId, phase, prereqChecked]);

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
        maxWidth: "1100px",
        margin: "0 auto",
        padding: "1.5rem 1.5rem 3rem",
      }}>
        {/* Customize this lesson — compact collapsible panel */}
        <div className="text-center mb-4">
          <button
            onClick={() => setShowCustomize(!showCustomize)}
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              fontSize: "0.75rem",
              color: "var(--color-text-muted)",
              fontFamily: "inherit",
              transition: "color 0.15s",
            }}
            onMouseEnter={(e) => (e.currentTarget.style.color = "var(--color-text)")}
            onMouseLeave={(e) => (e.currentTarget.style.color = "var(--color-text-muted)")}
          >
            {showCustomize ? "Hide customization \u25b4" : "Customize this lesson \u25be"}
          </button>
          {showCustomize && (
            <div style={{ marginTop: "0.5rem", display: "flex", flexDirection: "column", alignItems: "center", gap: "0.5rem" }}>
              <input
                style={{
                  width: "100%",
                  maxWidth: "320px",
                  padding: "0.375rem 0.75rem",
                  fontSize: "0.875rem",
                  backgroundColor: "var(--color-surface)",
                  border: "1px solid var(--color-border)",
                  borderRadius: "var(--radius-md)",
                  color: "var(--color-text)",
                  fontFamily: "inherit",
                  outline: "none",
                  transition: "border-color 0.15s",
                }}
                placeholder="Add interests (e.g. football, cooking)..."
                value={interestInput}
                onChange={(e) => setInterestInput(e.target.value)}
                onFocus={(e) => (e.target.style.borderColor = "var(--color-primary)")}
                onBlur={(e) => (e.target.style.borderColor = "var(--color-border)")}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && interestInput.trim()) {
                    setLessonInterests((prev) => [...prev, interestInput.trim()]);
                    setInterestInput("");
                  }
                }}
              />
              {lessonInterests.length > 0 && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: "0.25rem", justifyContent: "center" }}>
                  {lessonInterests.map((interest) => (
                    <span
                      key={interest}
                      onClick={() => setLessonInterests((prev) => prev.filter((i) => i !== interest))}
                      style={{
                        padding: "0.125rem 0.5rem",
                        fontSize: "0.75rem",
                        backgroundColor: "var(--color-primary-light)",
                        color: "var(--color-primary)",
                        borderRadius: "9999px",
                        cursor: "pointer",
                        fontWeight: 600,
                        transition: "background 0.15s, color 0.15s",
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.backgroundColor = "rgba(239,68,68,0.15)";
                        e.currentTarget.style.color = "#ef4444";
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.backgroundColor = "var(--color-primary-light)";
                        e.currentTarget.style.color = "var(--color-primary)";
                      }}
                    >
                      {interest}{" "}{"\u00d7"}
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Skeleton: mimics card layout */}
        <div style={{ display: "flex", gap: "1rem", alignItems: "flex-start" }}>
          <div style={{ flex: "1 1 0", minWidth: 0 }}>
            {/* Progress dots skeleton */}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "0.4rem", marginBottom: "1rem" }}>
              {[0,1,2,3].map(i => (
                <div key={i} className="skeleton-shimmer" style={{ width: i === 0 ? "28px" : "12px", height: "12px", borderRadius: "9999px" }} />
              ))}
            </div>
            {/* Card skeleton */}
            <div style={{
              backgroundColor: "var(--color-surface)",
              borderRadius: "var(--radius-lg)",
              border: "2px solid var(--color-border)",
              overflow: "hidden",
            }}>
              {/* Card header skeleton */}
              <div className="skeleton-shimmer" style={{ height: "64px", borderRadius: 0 }} />
              {/* Card body skeleton */}
              <div style={{ padding: "1.5rem 1.75rem" }}>
                <div className="skeleton-shimmer" style={{ height: "1rem", marginBottom: "0.6rem" }} />
                <div className="skeleton-shimmer" style={{ height: "1rem", width: "90%", marginBottom: "0.6rem" }} />
                <div className="skeleton-shimmer" style={{ height: "1rem", width: "75%", marginBottom: "1.5rem" }} />
                <div className="skeleton-shimmer" style={{ height: "2.8rem", marginBottom: "0.5rem", borderRadius: "9999px" }} />
                <div className="skeleton-shimmer" style={{ height: "2.8rem", marginBottom: "0.5rem", borderRadius: "9999px" }} />
                <div className="skeleton-shimmer" style={{ height: "2.8rem", borderRadius: "9999px" }} />
              </div>
            </div>
          </div>
          {/* Assistant panel skeleton */}
          <div style={{ width: "320px", flexShrink: 0 }}>
            <div className="skeleton-shimmer" style={{ height: "400px", borderRadius: "var(--radius-lg)" }} />
          </div>
        </div>
        <p style={{ textAlign: "center", color: "var(--color-text-muted)", marginTop: "1.5rem", fontSize: "0.95rem", fontWeight: 600 }}>
          {t("learning.craftingCards")}
        </p>
      </div>
    );
  }

  // Attempts exhausted — session ended without mastery
  if (phase === "ATTEMPTS_EXHAUSTED") {
    return (
      <div style={{
        maxWidth: "600px",
        margin: "0 auto",
        padding: "3rem 1.5rem",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: "1.25rem",
        textAlign: "center",
      }}>
        <div style={{
          width: "72px",
          height: "72px",
          borderRadius: "50%",
          backgroundColor: "color-mix(in srgb, var(--color-primary) 12%, var(--color-surface))",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: "2rem",
        }}>
          {"📚"}
        </div>
        <h2 style={{ fontWeight: 800, fontSize: "1.5rem", color: "var(--color-text)", margin: 0 }}>
          That was tough — but you gave it your best!
        </h2>
        <p style={{ color: "var(--color-text-muted)", fontSize: "1rem", lineHeight: 1.6, maxWidth: "480px", margin: 0 }}>
          You worked through three rounds on <strong>{conceptTitle}</strong> and scored{" "}
          <strong>{bestScore ?? checkScore ?? 0}%</strong> at your best. This concept needs a bit more time to click — and that is completely normal.
        </p>
        <p style={{ color: "var(--color-text-muted)", fontSize: "0.95rem", lineHeight: 1.5, maxWidth: "460px", margin: 0 }}>
          You can tap it on the Concept Map to start fresh whenever you are ready. Every attempt builds understanding.
        </p>
        <button
          onClick={() => { reset(); navigate("/map"); }}
          style={{
            display: "flex",
            alignItems: "center",
            gap: "0.5rem",
            padding: "0.75rem 1.75rem",
            borderRadius: "12px",
            border: "none",
            backgroundColor: "var(--color-primary)",
            color: "#fff",
            fontWeight: 700,
            fontSize: "1rem",
            cursor: "pointer",
            fontFamily: "inherit",
            boxShadow: "0 4px 12px rgba(var(--color-primary-rgb, 99,102,241), 0.3)",
            marginTop: "0.5rem",
          }}
        >
          <MapPin size={18} />
          Back to Concept Map
        </button>
      </div>
    );
  }

  // Determine max width based on phase
  const isCardPhase = phase === "CARDS" || phase === "REMEDIATING" || phase === "REMEDIATING_2";
  const isChatPhase = phase === "CHECKING" || phase === "RECHECKING" || phase === "RECHECKING_2";

  return (
    <div style={{
      maxWidth: isCardPhase ? "1100px" : "800px",
      margin: "0 auto",
      padding: "1.5rem 1.5rem 3rem",
    }}>
      {/* ── Prerequisite Warning Modal ── */}
      {prereqWarning && (
        <div style={{
          position: "fixed",
          inset: 0,
          zIndex: 1000,
          backgroundColor: "rgba(0, 0, 0, 0.55)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: "1rem",
        }}>
          <div style={{
            backgroundColor: "var(--color-bg-card)",
            borderRadius: "var(--radius-xl)",
            padding: "2rem",
            maxWidth: "480px",
            width: "100%",
            boxShadow: "0 20px 60px rgba(0,0,0,0.3)",
            display: "flex",
            flexDirection: "column",
            gap: "1rem",
          }}>
            {/* Header */}
            <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
              <AlertCircle size={28} color="var(--color-danger)" style={{ flexShrink: 0 }} />
              <h2 style={{
                margin: 0,
                fontSize: "1.25rem",
                fontWeight: 800,
                color: "var(--color-text)",
                lineHeight: 1.3,
              }}>
                Not quite ready yet!
              </h2>
            </div>

            {/* Subtitle */}
            <p style={{
              margin: 0,
              fontSize: "0.95rem",
              color: "var(--color-text-muted)",
              lineHeight: 1.6,
            }}>
              To get the most from this lesson, it helps to master these first:
            </p>

            {/* Unmet prerequisites list */}
            <ul style={{
              margin: 0,
              paddingLeft: "1.25rem",
              display: "flex",
              flexDirection: "column",
              gap: "0.35rem",
            }}>
              {prereqWarning.unmet.map((prereq) => (
                <li
                  key={prereq.concept_id}
                  style={{
                    fontSize: "0.95rem",
                    color: "var(--color-text)",
                    fontWeight: 600,
                    lineHeight: 1.5,
                  }}
                >
                  {prereq.concept_title}
                </li>
              ))}
            </ul>

            {/* Action buttons */}
            <div style={{
              display: "flex",
              gap: "0.75rem",
              marginTop: "0.5rem",
              flexWrap: "wrap",
            }}>
              <button
                onClick={() => {
                  setPrereqWarning(null);
                  navigate("/map");
                }}
                style={{
                  flex: "1 1 auto",
                  padding: "0.65rem 1.25rem",
                  borderRadius: "var(--radius-md)",
                  border: "none",
                  backgroundColor: "var(--color-primary)",
                  color: "#fff",
                  fontSize: "0.95rem",
                  fontWeight: 700,
                  cursor: "pointer",
                  fontFamily: "inherit",
                  transition: "opacity 0.15s",
                }}
                onMouseEnter={(e) => (e.currentTarget.style.opacity = "0.88")}
                onMouseLeave={(e) => (e.currentTarget.style.opacity = "1")}
              >
                Learn prerequisites first
              </button>
              <button
                onClick={() => {
                  const { style, interests } = prereqWarning;
                  setPrereqWarning(null);
                  startLesson(decodeURIComponent(conceptId), style, interests);
                }}
                style={{
                  flex: "1 1 auto",
                  padding: "0.65rem 1.25rem",
                  borderRadius: "var(--radius-md)",
                  border: "1px solid var(--color-border)",
                  backgroundColor: "transparent",
                  color: "var(--color-text-muted)",
                  fontSize: "0.95rem",
                  fontWeight: 600,
                  cursor: "pointer",
                  fontFamily: "inherit",
                  transition: "color 0.15s, border-color 0.15s",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.color = "var(--color-text)";
                  e.currentTarget.style.borderColor = "var(--color-text-muted)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.color = "var(--color-text-muted)";
                  e.currentTarget.style.borderColor = "var(--color-border)";
                }}
              >
                Start anyway
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Exit bar (CARDS + CHECKING + remediation + recheck phases) ── */}
      {(isCardPhase || isChatPhase) && (
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

      {/* Primary learning phases */}
      {phase === "CARDS" && <CardLearningView />}
      {phase === "CHECKING" && <SocraticChat />}
      {phase === "COMPLETED" && <CompletionView />}

      {/* Remediation phases — cards with remediation banner */}
      {(phase === "REMEDIATING" || phase === "REMEDIATING_2") && (
        <CardLearningView remediationMode={true} />
      )}

      {/* Re-check phases — Socratic chat with recheck banner */}
      {(phase === "RECHECKING" || phase === "RECHECKING_2") && (
        <SocraticChat recheckMode={true} />
      )}
    </div>
  );
}
