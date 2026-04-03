import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams, useNavigate } from "react-router-dom";
import { useSession } from "../context/SessionContext";
import { useStudent } from "../context/StudentContext";
import ProgressBar from "../components/learning/ProgressBar";
import VerticalProgressRail from "../components/learning/VerticalProgressRail";
import CardLearningView from "../components/learning/CardLearningView";
import SocraticChat from "../components/learning/SocraticChat";
import CompletionView from "../components/learning/CompletionView";
import { trackEvent } from "../utils/analytics";
import { AlertCircle, LogOut, MapPin } from "lucide-react";
import { checkConceptReadiness } from "../api/concepts";
import { getSession, getChunkList } from "../api/sessions";

export default function LearningPage() {
  const { t } = useTranslation();
  const { conceptId } = useParams();
  const navigate = useNavigate();
  const {
    phase, startLesson, error, reset,
    session, conceptTitle, currentCardIndex,
    cards, cardAnswers, messages,
    checkScore, bestScore,
    chunkList, chunkProgress, currentChunkId, currentChunkMode,
    allStudyComplete, submitChunkAnswers, chunkQuestions, chunkEvalResult,
    startChunk, dispatch, loading,
  } = useSession();
  const { student } = useStudent();

  const [prereqWarning, setPrereqWarning] = useState(null);
  const [prereqChecked, setPrereqChecked] = useState(false);
  const [chunkAnswers, setChunkAnswers] = useState({});

  // Per-chunk picker state
  const [selectedChunkId, setSelectedChunkId] = useState(null);
  const [chunkStyle, setChunkStyle] = useState("default");
  const [chunkInterests, setChunkInterests] = useState([]);
  const [chunkInterestInput, setChunkInterestInput] = useState("");

  useEffect(() => {
    if (conceptId && phase === "IDLE" && !prereqChecked) {
      setPrereqChecked(true);
      const decodedConceptId = decodeURIComponent(conceptId);

      const launchLesson = () => startLesson(decodedConceptId, null, []);

      const tryResume = () => {
        const savedSessionId = localStorage.getItem(`ada_session_${decodedConceptId}`);
        if (savedSessionId) {
          getSession(savedSessionId)
            .then(res => {
              const existing = res.data;
              if (existing && existing.phase !== "DONE") {
                // Restore session state then load chunk list to resume at SELECTING_CHUNK
                dispatch({ type: "SESSION_CREATED", payload: existing });
                return getChunkList(existing.id).then(chunkRes => {
                  const chunkListData = chunkRes.data;
                  if (chunkListData.chunks && chunkListData.chunks.length > 0) {
                    dispatch({ type: "CHUNK_LIST_LOADED", payload: chunkListData });
                  } else {
                    launchLesson();
                  }
                });
              } else {
                launchLesson();
              }
            })
            .catch(() => launchLesson());
        } else {
          launchLesson();
        }
      };

      checkConceptReadiness(decodedConceptId, student.id)
        .then(res => {
          const data = res.data;
          if (!data.all_prerequisites_met && data.unmet_prerequisites.length > 0) {
            setPrereqWarning({ unmet: data.unmet_prerequisites });
          } else {
            tryResume();
          }
        })
        .catch((err) => {
          console.error("[LearningPage] prereq check failed:", err);
          launchLesson();
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
        minHeight: "100vh", gap: "1rem", padding: "2rem",
      }}>
        <AlertCircle size={48} color="var(--color-danger)" />
        <h2 style={{ color: "var(--color-danger)", fontWeight: 700 }}>{t("common.error")}</h2>
        <p style={{ color: "var(--color-text-muted)", textAlign: "center", maxWidth: "400px" }}>
          {error}
        </p>
        <div style={{ display: "flex", gap: "0.75rem" }}>
          <button
            onClick={() => {
              if (phase === "SELECTING_CHUNK") {
                dispatch({ type: "CLEAR_ERROR" });
              } else {
                reset();
                startLesson(decodeURIComponent(conceptId), null, []);
              }
            }}
            style={{
              padding: "0.6rem 1.5rem", borderRadius: "10px", border: "none",
              backgroundColor: "var(--color-primary)", color: "#fff",
              fontSize: "1rem", fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
            }}
          >
            {t("learning.tryAgain")}
          </button>
          <button
            onClick={() => { reset(); navigate("/map"); }}
            style={{
              padding: "0.6rem 1.5rem", borderRadius: "10px",
              border: "1.5px solid var(--color-primary)", backgroundColor: "transparent",
              color: "var(--color-primary)",
              fontSize: "1rem", fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
            }}
          >
            {t("learning.backToMap")}
          </button>
        </div>
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
          {t("learning.toughLesson")}
        </h2>
        <p style={{ color: "var(--color-text-muted)", fontSize: "1rem", lineHeight: 1.6, maxWidth: "480px", margin: 0 }}>
          {t("learning.attemptsExhausted.body", { title: conceptTitle, score: bestScore ?? checkScore ?? 0 })}
        </p>
        <p style={{ color: "var(--color-text-muted)", fontSize: "0.95rem", lineHeight: 1.5, maxWidth: "460px", margin: 0 }}>
          {t("learning.attemptsExhausted.encouragement")}
        </p>
        <div style={{ display: "flex", gap: "0.75rem", marginTop: "0.5rem", flexWrap: "wrap", justifyContent: "center" }}>
          <button
            onClick={() => { reset(); startLesson(decodeURIComponent(conceptId), null, []); }}
            style={{
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
            }}
          >
            {t("learning.attemptsExhausted.tryAgain")}
          </button>
          <button
            onClick={() => { reset(); navigate("/map"); }}
            style={{
              display: "flex",
              alignItems: "center",
              gap: "0.5rem",
              padding: "0.75rem 1.75rem",
              borderRadius: "12px",
              border: "1px solid var(--color-border)",
              backgroundColor: "transparent",
              color: "var(--color-text-muted)",
              fontWeight: 700,
              fontSize: "1rem",
              cursor: "pointer",
              fontFamily: "inherit",
            }}
          >
            <MapPin size={18} />
            {t("learning.backToMap")}
          </button>
        </div>
      </div>
    );
  }

  // ── Subsection picker ──────────────────────────────────────────────────────
  if (phase === "SELECTING_CHUNK") {
    const visibleChunks = (chunkList || []).slice().sort((a, b) => {
      if (a.chunk_type === "chapter_review" && b.chunk_type !== "chapter_review") return 1;
      if (b.chunk_type === "chapter_review" && a.chunk_type !== "chapter_review") return -1;
      return (a.order_index ?? 0) - (b.order_index ?? 0);
    });

    const handleStartClick = (chunkId) => {
      if (selectedChunkId === chunkId) {
        setSelectedChunkId(null); // collapse if already open
      } else {
        setSelectedChunkId(chunkId);
        setChunkStyle("default");
        setChunkInterests([]);
        setChunkInterestInput("");
      }
    };

    const handleStartLearning = async (chunkId) => {
      setSelectedChunkId(null);
      await startChunk(chunkId, chunkStyle, chunkInterests);
    };

    // Mode badge helpers
    const firstUncompletedIdx = visibleChunks.findIndex(
      (c) => c.chunk_type !== "exercise_gate"
        && c.chunk_type !== "learning_objective"
        && !(c.chunk_id in (chunkProgress || {}))
    );

    const modeBadgeLabel = (mode) => t(`learning.mode.${mode}`, mode);

    return (
      <div style={{
        maxWidth: "760px",
        margin: "0 auto",
        padding: "2rem 1.5rem 4rem",
      }}>
        {/* Prerequisite Warning Modal */}
        {prereqWarning && (
          <div style={{
            position: "fixed", inset: 0, zIndex: 1000,
            backgroundColor: "rgba(0,0,0,0.6)",
            backdropFilter: "blur(4px)",
            display: "flex", alignItems: "center", justifyContent: "center", padding: "1rem",
          }}>
            <div style={{
              backgroundColor: "var(--color-surface)",
              borderRadius: "var(--radius-xl)",
              padding: "2rem",
              maxWidth: "480px", width: "100%",
              boxShadow: "0 24px 64px rgba(0,0,0,0.4)",
              border: "1px solid var(--color-border-strong, var(--color-border))",
              display: "flex", flexDirection: "column", gap: "1rem",
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
                <AlertCircle size={28} color="var(--color-danger)" style={{ flexShrink: 0 }} />
                <h2 style={{ margin: 0, fontSize: "1.25rem", fontWeight: 800, color: "var(--color-text)", lineHeight: 1.3 }}>
                  {t("learning.notReadyYet")}
                </h2>
              </div>
              <p style={{ margin: 0, fontSize: "0.95rem", color: "var(--color-text-muted)", lineHeight: 1.6 }}>
                {t("learning.helpsMasterFirst")}
              </p>
              <ul style={{ margin: 0, paddingLeft: "1.25rem", display: "flex", flexDirection: "column", gap: "0.35rem" }}>
                {prereqWarning.unmet.map((prereq) => (
                  <li key={prereq.concept_id} style={{ fontSize: "0.95rem", color: "var(--color-text)", fontWeight: 600, lineHeight: 1.5 }}>
                    {prereq.concept_title}
                  </li>
                ))}
              </ul>
              <div style={{ display: "flex", gap: "0.75rem", marginTop: "0.5rem", flexWrap: "wrap" }}>
                <button onClick={() => { setPrereqWarning(null); navigate("/map"); }}
                  style={{ flex: "1 1 auto", padding: "0.65rem 1.25rem", borderRadius: "var(--radius-md)", border: "none", backgroundColor: "var(--color-primary)", color: "#fff", fontSize: "0.95rem", fontWeight: 700, cursor: "pointer", fontFamily: "inherit" }}>
                  {t("learning.learnPrereqFirst")}
                </button>
                <button onClick={() => { setPrereqWarning(null); startLesson(decodeURIComponent(conceptId), null, []); }}
                  style={{ flex: "1 1 auto", padding: "0.65rem 1.25rem", borderRadius: "var(--radius-md)", border: "1px solid var(--color-border-strong, var(--color-border))", backgroundColor: "transparent", color: "var(--color-text-muted)", fontSize: "0.95rem", fontWeight: 600, cursor: "pointer", fontFamily: "inherit" }}>
                  {t("learning.startAnyway")}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Page header */}
        <div style={{ marginBottom: "2rem" }}>
          <h1 style={{
            margin: 0,
            fontSize: "1.5rem",
            fontWeight: 800,
            color: "var(--color-text)",
            letterSpacing: "-0.02em",
          }}>
            {conceptTitle || t("learning.chooseSubsection", "Choose a subsection to start")}
          </h1>
          {chunkProgress && Object.keys(chunkProgress).length > 0 && (
            <p style={{ margin: "0.4rem 0 0", fontSize: "0.85rem", color: "var(--color-text-muted)", fontWeight: 500 }}>
              {Object.keys(chunkProgress).length} of {visibleChunks.length} sections completed
            </p>
          )}
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
          {visibleChunks.map((chunk, idx) => {
            const isDone = chunk.chunk_id in (chunkProgress || {});
            const score = chunkProgress?.[chunk.chunk_id]?.score;
            const isOptional = chunk.is_optional === true;
            const isInfoPanel = chunk.chunk_type === "learning_objective";
            const isReview = chunk.chunk_type === "chapter_review";
            const isExpanded = selectedChunkId === chunk.chunk_id;
            const prevRequired = visibleChunks.slice(0, idx).filter(
              (c) => c.chunk_type !== "learning_objective"
            );
            const isLocked = !isInfoPanel
              && prevRequired.length > 0
              && !(prevRequired[prevRequired.length - 1]?.chunk_id in (chunkProgress || {}));

            const statusColor = isDone
              ? "var(--color-success)"
              : isLocked
                ? "var(--color-text-muted)"
                : "var(--color-primary)";

            const statusIcon = isDone ? "✓" : isLocked ? "🔒" : `${idx + 1}`;

            return (
              <div
                key={chunk.chunk_id}
                style={{
                  borderRadius: "14px",
                  border: isExpanded
                    ? "2px solid var(--color-primary)"
                    : isDone
                      ? "1.5px solid rgba(74,222,128,0.25)"
                      : "1.5px solid var(--color-border-strong, rgba(255,255,255,0.15))",
                  background: isExpanded
                    ? "var(--color-primary-light)"
                    : isDone
                      ? "color-mix(in srgb, var(--color-success) 6%, var(--color-surface))"
                      : "var(--color-surface)",
                  overflow: "hidden",
                  transition: "border-color 0.15s, background 0.15s",
                }}
              >
                {/* Main row */}
                <div style={{
                  padding: "14px 18px",
                  display: "flex",
                  alignItems: "center",
                  gap: "14px",
                }}>
                  {/* Number/status circle */}
                  <div style={{
                    width: "34px",
                    height: "34px",
                    borderRadius: "50%",
                    flexShrink: 0,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: isDone ? "16px" : "13px",
                    fontWeight: 700,
                    backgroundColor: isDone
                      ? "rgba(74,222,128,0.15)"
                      : isLocked
                        ? "rgba(255,255,255,0.06)"
                        : "var(--color-primary-light)",
                    color: statusColor,
                    border: `1.5px solid ${isDone ? "rgba(74,222,128,0.3)" : isLocked ? "rgba(255,255,255,0.1)" : "rgba(99,102,241,0.3)"}`,
                  }}>
                    {statusIcon}
                  </div>

                  {/* Heading + badges */}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{
                      fontSize: "14px",
                      fontWeight: isDone ? 500 : 600,
                      color: isLocked ? "var(--color-text-muted)" : "var(--color-text)",
                      lineHeight: 1.4,
                      marginBottom: "3px",
                    }}>
                      {chunk.heading}
                    </div>
                    <div style={{ display: "flex", gap: "6px", flexWrap: "wrap", alignItems: "center" }}>
                      {isDone && score != null && (
                        <span style={{
                          fontSize: "11px",
                          fontWeight: 700,
                          color: score >= 80 ? "var(--color-success)" : score >= 50 ? "var(--color-primary)" : "var(--color-danger)",
                        }}>
                          {score}% score
                        </span>
                      )}
                      {isDone && chunkProgress?.[chunk.chunk_id]?.mode_used && (
                        <span style={{
                          fontSize: "10px", fontWeight: 600, padding: "1px 7px", borderRadius: "9999px",
                          backgroundColor: "rgba(255,255,255,0.08)",
                          color: "var(--color-text-muted)",
                        }}>
                          {modeBadgeLabel(chunkProgress[chunk.chunk_id].mode_used)}
                        </span>
                      )}
                      {!isDone && !isInfoPanel && chunk.chunk_type !== "exercise_gate" && idx === firstUncompletedIdx && currentChunkMode && (
                        <span style={{
                          fontSize: "10px", fontWeight: 600, padding: "1px 7px", borderRadius: "9999px",
                          backgroundColor: "var(--color-primary-light)",
                          color: "var(--color-primary)",
                          border: "1px dashed rgba(99,102,241,0.4)",
                        }}>
                          {modeBadgeLabel(currentChunkMode)} mode
                        </span>
                      )}
                      {isOptional && (
                        <span style={{
                          fontSize: "10px", fontWeight: 600, padding: "1px 7px", borderRadius: "9999px",
                          backgroundColor: "rgba(251,191,36,0.12)", color: "var(--color-warning)",
                        }}>
                          {t("subsectionNav.optional", "Optional")}
                        </span>
                      )}
                      {isReview && (
                        <span style={{
                          fontSize: "10px", fontWeight: 600, padding: "1px 7px", borderRadius: "9999px",
                          backgroundColor: "rgba(99,102,241,0.12)", color: "var(--color-primary)",
                        }}>
                          {t("subsectionNav.review", "Review")}
                        </span>
                      )}
                      {isInfoPanel && (
                        <span style={{
                          fontSize: "10px", fontWeight: 600, padding: "1px 7px", borderRadius: "9999px",
                          backgroundColor: "rgba(74,222,128,0.1)", color: "var(--color-success)",
                        }}>
                          {t("subsectionNav.info", "Info")}
                        </span>
                      )}
                      {isLocked && (
                        <span style={{
                          fontSize: "10px", fontWeight: 500, color: "var(--color-text-muted)",
                        }}>
                          {t("subsectionNav.lockedSubsection", "Complete previous section first")}
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Action button */}
                  {!isLocked && (
                    <button
                      disabled={loading}
                      onClick={() =>
                        isInfoPanel
                          ? handleStartLearning(chunk.chunk_id)
                          : handleStartClick(chunk.chunk_id)
                      }
                      style={{
                        padding: "7px 18px",
                        borderRadius: "9999px",
                        border: isDone
                          ? "1.5px solid var(--color-border-strong, var(--color-border))"
                          : "none",
                        background: isDone
                          ? "transparent"
                          : isExpanded
                            ? "rgba(99,102,241,0.15)"
                            : "var(--color-primary)",
                        color: isDone
                          ? "var(--color-text-muted)"
                          : isExpanded
                            ? "var(--color-primary)"
                            : "#fff",
                        fontSize: "13px",
                        fontWeight: 700,
                        cursor: loading ? "not-allowed" : "pointer",
                        fontFamily: "inherit",
                        opacity: loading ? 0.6 : 1,
                        flexShrink: 0,
                        transition: "all 0.15s",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {isDone
                        ? (isExpanded ? "▲" : t("map.reviewLesson", "Review"))
                        : isExpanded
                          ? "▲"
                          : t("learning.startSubsection", "Start")
                      }
                    </button>
                  )}
                  {isLocked && (
                    <div style={{
                      width: "34px", height: "34px", flexShrink: 0,
                      display: "flex", alignItems: "center", justifyContent: "center",
                      opacity: 0.35,
                    }}>
                      🔒
                    </div>
                  )}
                </div>

                {/* Expanded customization panel */}
                {isExpanded && (
                  <div style={{
                    borderTop: "1px solid var(--color-border)",
                    padding: "16px 18px 18px",
                    backgroundColor: "var(--color-bg)",
                    display: "flex",
                    flexDirection: "column",
                    gap: "14px",
                  }}>
                    {/* Style picker */}
                    <div>
                      <div style={{
                        fontSize: "11px", fontWeight: 700, textTransform: "uppercase",
                        letterSpacing: "0.06em", color: "var(--color-text-muted)",
                        marginBottom: "8px",
                      }}>
                        {t("customize.style", "Tutor style")}
                      </div>
                      <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                        {[
                          { id: "default", label: t("style.default", "Default"), emoji: "📖" },
                          { id: "pirate", label: t("style.pirate", "Pirate"), emoji: "🏴‍☠️" },
                          { id: "astronaut", label: t("style.astronaut", "Space"), emoji: "🚀" },
                          { id: "gamer", label: t("style.gamer", "Gamer"), emoji: "🎮" },
                        ].map(({ id, label, emoji }) => (
                          <button
                            key={id}
                            onClick={() => setChunkStyle(id)}
                            style={{
                              padding: "6px 14px",
                              borderRadius: "9999px",
                              border: chunkStyle === id
                                ? "2px solid var(--color-primary)"
                                : "1.5px solid var(--color-border-strong, var(--color-border))",
                              background: chunkStyle === id ? "var(--color-primary-light)" : "transparent",
                              color: chunkStyle === id ? "var(--color-primary)" : "var(--color-text-muted)",
                              fontSize: "12px", fontWeight: 600,
                              cursor: "pointer", fontFamily: "inherit",
                              transition: "all 0.15s",
                            }}
                          >
                            {emoji} {label}
                          </button>
                        ))}
                      </div>
                    </div>

                    {/* Interests */}
                    <div>
                      <div style={{
                        fontSize: "11px", fontWeight: 700, textTransform: "uppercase",
                        letterSpacing: "0.06em", color: "var(--color-text-muted)",
                        marginBottom: "8px",
                      }}>
                        {t("customize.interests", "Interests")} <span style={{ fontWeight: 400, textTransform: "none", letterSpacing: 0 }}>(optional — makes examples fun)</span>
                      </div>
                      <div style={{ display: "flex", gap: "8px", flexWrap: "wrap", marginBottom: chunkInterests.length > 0 ? "8px" : 0 }}>
                        {chunkInterests.map((interest) => (
                          <span
                            key={interest}
                            onClick={() => setChunkInterests((prev) => prev.filter((i) => i !== interest))}
                            style={{
                              padding: "4px 10px",
                              borderRadius: "9999px",
                              background: "var(--color-primary-light)",
                              color: "var(--color-primary)",
                              fontSize: "12px", fontWeight: 600,
                              cursor: "pointer",
                              border: "1px solid rgba(99,102,241,0.3)",
                            }}
                          >
                            {interest} ✕
                          </span>
                        ))}
                      </div>
                      <input
                        value={chunkInterestInput}
                        onChange={(e) => setChunkInterestInput(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && chunkInterestInput.trim()) {
                            setChunkInterests((prev) => [...new Set([...prev, chunkInterestInput.trim()])]);
                            setChunkInterestInput("");
                          }
                        }}
                        placeholder={t("customize.addInterest", "Type topic and press Enter...")}
                        style={{
                          width: "100%",
                          padding: "8px 12px",
                          borderRadius: "10px",
                          border: "1.5px solid var(--color-border-strong, var(--color-border))",
                          background: "var(--color-surface)",
                          color: "var(--color-text)",
                          fontSize: "13px",
                          fontFamily: "inherit",
                          outline: "none",
                          boxSizing: "border-box",
                        }}
                      />
                    </div>

                    {/* Start button */}
                    <button
                      onClick={() => handleStartLearning(chunk.chunk_id)}
                      disabled={loading}
                      style={{
                        padding: "12px",
                        borderRadius: "12px",
                        border: "none",
                        background: "var(--color-primary)",
                        color: "#fff",
                        fontSize: "15px",
                        fontWeight: 700,
                        cursor: loading ? "not-allowed" : "pointer",
                        fontFamily: "inherit",
                        opacity: loading ? 0.7 : 1,
                        boxShadow: "0 4px 16px rgba(99,102,241,0.3)",
                        transition: "opacity 0.15s",
                      }}
                    >
                      {loading ? t("learning.gettingReady", "Getting ready...") : `▶  ${t("learning.startLearning", "Start Learning")}`}
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  // ── Per-chunk typed Q&A ────────────────────────────────────────────────────
  if (phase === "CHUNK_QUESTIONS") {
    const evalResult = chunkEvalResult;
    const allAnswered = chunkQuestions.every((_, i) => (chunkAnswers[i] || "").trim().length > 0);

    return (
      <div style={{ maxWidth: "700px", margin: "0 auto", padding: "2rem 1.5rem 3rem" }}>
        {!evalResult && (
          <div style={{ marginBottom: "1.25rem" }}>
            <button
              onClick={() => dispatch({ type: "RETURN_TO_PICKER" })}
              style={{
                background: "none", border: "none", cursor: "pointer",
                color: "var(--color-text-muted)", fontSize: "0.875rem",
                padding: "0.25rem 0", display: "flex", alignItems: "center", gap: "0.35rem",
              }}
            >
              ← {t("nav.backToSubsections", "Back to subsections")}
            </button>
          </div>
        )}
        <h2 style={{ fontWeight: 800, fontSize: "1.3rem", color: "var(--color-text)", marginBottom: "0.25rem" }}>
          {t("chunkQuestions.title", "Knowledge Check")}
        </h2>
        <p style={{ color: "var(--color-text-muted)", fontSize: "0.9rem", marginBottom: "1.5rem" }}>
          {t("chunkQuestions.instruction", "Answer in your own words — no need to be exact.")}
        </p>

        {!evalResult && chunkQuestions.map((q, i) => (
          <div key={q.index} style={{
            marginBottom: "1.25rem",
            padding: "1rem 1.25rem",
            borderRadius: "10px",
            border: "1px solid var(--color-border)",
            backgroundColor: "var(--color-surface)",
          }}>
            <p style={{ fontWeight: 700, fontSize: "1rem", color: "var(--color-text)", marginBottom: "0.5rem", lineHeight: 1.5 }}>
              Q{i + 1}. {q.text}
            </p>
            <textarea
              value={chunkAnswers[i] || ""}
              onChange={(e) => setChunkAnswers((prev) => ({ ...prev, [i]: e.target.value }))}
              placeholder={t("chunkQuestions.placeholder", "Type your answer here...")}
              rows={3}
              style={{
                width: "100%",
                borderRadius: "8px",
                padding: "0.75rem",
                fontSize: "0.95rem",
                border: "2px solid var(--color-border)",
                backgroundColor: "var(--color-background, var(--color-surface))",
                color: "var(--color-text)",
                fontFamily: "inherit",
                boxSizing: "border-box",
                resize: "vertical",
              }}
            />
          </div>
        ))}

        {evalResult && (
          <div style={{
            padding: "1.25rem",
            borderRadius: "12px",
            backgroundColor: evalResult.passed ? "rgba(22,163,74,0.07)" : "rgba(239,68,68,0.07)",
            border: `1.5px solid ${evalResult.passed ? "rgba(22,163,74,0.3)" : "rgba(239,68,68,0.3)"}`,
            marginBottom: "1.5rem",
          }}>
            <div style={{ fontSize: "1.3rem", fontWeight: 800, color: evalResult.passed ? "#16a34a" : "#dc2626", marginBottom: "0.3rem" }}>
              {evalResult.passed
                ? `✓ ${t("chunkQuestions.passed", "Passed")} ${Math.round(evalResult.score * 100)}%`
                : `✗ ${Math.round(evalResult.score * 100)}% — ${t("chunkQuestions.failed", "Not quite — let's review")}`}
            </div>
            {evalResult.passed && (
              <p style={{ color: "var(--color-text-muted)", fontSize: "0.9rem", margin: 0 }}>
                {evalResult.all_study_complete
                  ? t("chunkQuestions.completing", "Completing concept...")
                  : t("chunkQuestions.continuing", "Continuing...")}
              </p>
            )}
            {!evalResult.passed && evalResult.feedback?.length > 0 && (
              <div style={{ marginTop: "1rem" }}>
                {evalResult.feedback.map((fb, i) => (
                  <div key={i} style={{
                    marginBottom: "0.75rem",
                    padding: "0.6rem 0.9rem",
                    borderRadius: "8px",
                    border: `1px solid ${fb.correct ? "rgba(22,163,74,0.2)" : "rgba(239,68,68,0.2)"}`,
                    backgroundColor: fb.correct ? "rgba(22,163,74,0.04)" : "rgba(239,68,68,0.04)",
                  }}>
                    <span style={{ fontWeight: 700, color: fb.correct ? "#16a34a" : "#dc2626", marginRight: "6px" }}>
                      {fb.correct
                        ? `✓ ${t("chunkQuestions.correct", "Correct")}`
                        : `✗ ${t("chunkQuestions.incorrect", "Incorrect")}`}
                    </span>
                    <span style={{ color: "var(--color-text)", fontSize: "0.9rem" }}>{fb.feedback}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        <div style={{ display: "flex", gap: "0.75rem", justifyContent: "flex-end", flexWrap: "wrap" }}>
          {!evalResult && (
            <button
              disabled={!allAnswered || loading}
              onClick={() => {
                const answersPayload = chunkQuestions.map((q, i) => ({
                  index: q.index,
                  answer_text: chunkAnswers[i] || "",
                }));
                submitChunkAnswers(currentChunkId, chunkQuestions, answersPayload, currentChunkMode);
              }}
              style={{
                padding: "0.75rem 2rem",
                borderRadius: "10px",
                border: "none",
                backgroundColor: allAnswered && !loading ? "var(--color-primary)" : "var(--color-border)",
                color: allAnswered && !loading ? "#fff" : "var(--color-text-muted)",
                fontWeight: 700,
                fontSize: "1rem",
                cursor: allAnswered && !loading ? "pointer" : "not-allowed",
                fontFamily: "inherit",
              }}
            >
              {loading ? t("common.loading") : t("chunkQuestions.submit", "Submit Answers")}
            </button>
          )}
          {evalResult && !evalResult.passed && (
            <>
              <button
                onClick={() => {
                  setChunkAnswers({});
                  dispatch({ type: "RETURN_TO_PICKER" });
                }}
                style={{
                  padding: "0.75rem 1.75rem",
                  borderRadius: "10px",
                  border: "1.5px solid var(--color-border)",
                  backgroundColor: "transparent",
                  color: "var(--color-text-muted)",
                  fontWeight: 600,
                  fontSize: "1rem",
                  cursor: "pointer",
                  fontFamily: "inherit",
                }}
              >
                ← {t("nav.backToSubsections", "Back to subsection list")}
              </button>
              <button
                onClick={() => {
                  setChunkAnswers({});
                  startChunk(currentChunkId, currentChunkMode);
                }}
                style={{
                  padding: "0.75rem 1.75rem",
                  borderRadius: "10px",
                  border: "none",
                  backgroundColor: "var(--color-primary)",
                  color: "#fff",
                  fontWeight: 700,
                  fontSize: "1rem",
                  cursor: "pointer",
                  fontFamily: "inherit",
                }}
              >
                {t("chunkQuestions.restudy", "Re-study this section")}
              </button>
            </>
          )}
        </div>
      </div>
    );
  }

  // Determine max width based on phase
  const isCardPhase = phase === "CARDS" || phase === "REMEDIATING" || phase === "REMEDIATING_2";
  const isChatPhase = phase === "CHECKING" || phase === "RECHECKING" || phase === "RECHECKING_2";

  return (
    <div style={{
      maxWidth: isCardPhase ? "1200px" : "800px",
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
                {t("learning.notReadyYet")}
              </h2>
            </div>

            {/* Subtitle */}
            <p style={{
              margin: 0,
              fontSize: "0.95rem",
              color: "var(--color-text-muted)",
              lineHeight: 1.6,
            }}>
              {t("learning.helpsMasterFirst")}
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
                {t("learning.learnPrereqFirst")}
              </button>
              <button
                onClick={() => {
                  setPrereqWarning(null);
                  startLesson(decodeURIComponent(conceptId), null, []);
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
                {t("learning.startAnyway")}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Exit bar (Socratic check phases only — cards phase uses "Back to subsections" instead) ── */}
      {isChatPhase && (
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
      {phase === "CARDS" && (
        <div style={{ display: "flex", gap: "0.75rem", alignItems: "flex-start" }}>
          <VerticalProgressRail total={cards?.length ?? 0} current={currentCardIndex} cardStates={{}} />
          <div style={{ flex: 1, minWidth: 0 }}>
            {chunkList?.length > 0 && (
              <div style={{ marginBottom: "0.75rem" }}>
                <button
                  onClick={() => dispatch({ type: "RETURN_TO_PICKER" })}
                  style={{
                    background: "none", border: "none", cursor: "pointer",
                    color: "var(--color-primary)", fontSize: "0.875rem",
                    padding: "0.25rem 0.5rem", display: "flex", alignItems: "center", gap: "0.25rem",
                  }}
                >
                  ← {t("nav.backToSubsections", "Back to subsections")}
                </button>
              </div>
            )}
            <CardLearningView />
          </div>
        </div>
      )}
      {phase === "CHECKING" && <SocraticChat />}
      {phase === "COMPLETED" && <CompletionView />}

      {/* Remediation phases — cards with remediation banner */}
      {(phase === "REMEDIATING" || phase === "REMEDIATING_2") && (
        <div style={{ display: "flex", gap: "0.75rem", alignItems: "flex-start" }}>
          <VerticalProgressRail total={cards?.length ?? 0} current={currentCardIndex} cardStates={{}} />
          <div style={{ flex: 1, minWidth: 0 }}>
            {chunkList?.length > 0 && (
              <div style={{ marginBottom: "0.75rem" }}>
                <button
                  onClick={() => dispatch({ type: "RETURN_TO_PICKER" })}
                  style={{
                    background: "none", border: "none", cursor: "pointer",
                    color: "var(--color-primary)", fontSize: "0.875rem",
                    padding: "0.25rem 0.5rem", display: "flex", alignItems: "center", gap: "0.25rem",
                  }}
                >
                  ← {t("nav.backToSubsections", "Back to subsections")}
                </button>
              </div>
            )}
            <CardLearningView remediationMode={true} />
          </div>
        </div>
      )}

      {/* Re-check phases — Socratic chat with recheck banner */}
      {(phase === "RECHECKING" || phase === "RECHECKING_2") && (
        <SocraticChat recheckMode={true} />
      )}
    </div>
  );
}
