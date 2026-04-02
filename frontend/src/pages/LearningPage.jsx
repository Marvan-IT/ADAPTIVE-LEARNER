import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams, useNavigate } from "react-router-dom";
import { useSession } from "../context/SessionContext";
import { useStudent } from "../context/StudentContext";
import ProgressBar from "../components/learning/ProgressBar";
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
        minHeight: "calc(100vh - 64px)", gap: "1rem", padding: "2rem",
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
          {t("learning.backToMap")}
        </button>
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

    const modeBadgeStyle = (mode, predicted = false) => ({
      display: "inline-block",
      fontSize: "10px",
      fontWeight: 600,
      padding: "1px 6px",
      borderRadius: "10px",
      marginLeft: "6px",
      opacity: predicted ? 0.6 : 1,
      border: predicted ? "1px dashed currentColor" : "none",
      background: predicted ? "transparent" : (
        mode === "STRUGGLING" ? "#fbbf24" :
        mode === "FAST" ? "#22c55e" : "#60a5fa"
      ),
      color: predicted ? (
        mode === "STRUGGLING" ? "#d97706" :
        mode === "FAST" ? "#16a34a" : "#2563eb"
      ) : "#fff",
    });

    const modeBadgeLabel = (mode) =>
      mode === "STRUGGLING" ? "Struggling" : mode === "FAST" ? "Fast" : "Normal";

    return (
      <div style={{
        maxWidth: "700px",
        margin: "0 auto",
        padding: "2rem 1.5rem 3rem",
      }}>
        {/* Prerequisite Warning Modal */}
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
                <button
                  onClick={() => { setPrereqWarning(null); navigate("/map"); }}
                  style={{
                    flex: "1 1 auto", padding: "0.65rem 1.25rem", borderRadius: "var(--radius-md)",
                    border: "none", backgroundColor: "var(--color-primary)", color: "#fff",
                    fontSize: "0.95rem", fontWeight: 700, cursor: "pointer", fontFamily: "inherit",
                  }}
                >
                  {t("learning.learnPrereqFirst")}
                </button>
                <button
                  onClick={() => {
                    setPrereqWarning(null);
                    startLesson(decodeURIComponent(conceptId), null, []);
                  }}
                  style={{
                    flex: "1 1 auto", padding: "0.65rem 1.25rem", borderRadius: "var(--radius-md)",
                    border: "1px solid var(--color-border)", backgroundColor: "transparent",
                    color: "var(--color-text-muted)", fontSize: "0.95rem", fontWeight: 600,
                    cursor: "pointer", fontFamily: "inherit",
                  }}
                >
                  {t("learning.startAnyway")}
                </button>
              </div>
            </div>
          </div>
        )}

        <h2 style={{ fontWeight: 700, fontSize: "1.3rem", color: "var(--color-text)", marginBottom: "1.25rem" }}>
          {t("learning.chooseSubsection", "Choose a subsection to start")}
        </h2>

        <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
          {visibleChunks.map((chunk, idx) => {
            const isDone = chunk.chunk_id in (chunkProgress || {});
            const score = chunkProgress?.[chunk.chunk_id]?.score;
            const isOptional = chunk.is_optional === true;
            const isInfoPanel = chunk.chunk_type === "learning_objective";
            const isReview = chunk.chunk_type === "chapter_review";
            const isExpanded = selectedChunkId === chunk.chunk_id;
            // Only lock against previous non-info chunks
            const prevRequired = visibleChunks.slice(0, idx).filter(
              (c) => c.chunk_type !== "learning_objective"
            );
            const isLocked = !isInfoPanel
              && prevRequired.length > 0
              && !(prevRequired[prevRequired.length - 1]?.chunk_id in (chunkProgress || {}));

            return (
              <div
                key={chunk.chunk_id}
                style={{
                  borderRadius: "12px",
                  border: isExpanded
                    ? "1.5px solid var(--color-primary)"
                    : "1px solid var(--color-border)",
                  background: "var(--color-surface)",
                  overflow: "hidden",
                }}
              >
                {/* Chunk row */}
                <div style={{
                  padding: "12px 16px",
                  display: "flex",
                  alignItems: "center",
                  gap: "10px",
                }}>
                  {/* Status icon */}
                  <span style={{
                    fontSize: "16px",
                    flexShrink: 0,
                    color: isDone ? "#16a34a" : "var(--color-text-muted)",
                  }}>
                    {isDone ? "✓" : isLocked ? "🔒" : "○"}
                  </span>

                  {/* Heading */}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <span style={{
                      fontSize: "14px",
                      color: "var(--color-text)",
                      fontWeight: isDone ? 400 : 500,
                      lineHeight: 1.4,
                    }}>
                      {chunk.heading}
                      {/* Mode badge: shown for completed chunks (actual mode) or first uncompleted (predicted) */}
                      {isDone && chunkProgress?.[chunk.chunk_id]?.mode_used && (
                        <span style={modeBadgeStyle(chunkProgress[chunk.chunk_id].mode_used, false)}>
                          {modeBadgeLabel(chunkProgress[chunk.chunk_id].mode_used)}
                        </span>
                      )}
                      {!isDone && !isInfoPanel && chunk.chunk_type !== "exercise_gate" && idx === firstUncompletedIdx && currentChunkMode && (
                        <span style={modeBadgeStyle(currentChunkMode, true)}>
                          {modeBadgeLabel(currentChunkMode)}
                        </span>
                      )}
                    </span>
                    <div style={{ display: "flex", gap: "6px", marginTop: "2px", flexWrap: "wrap" }}>
                      {isDone && score != null && (
                        <span style={{
                          fontSize: "11px",
                          color: score >= 80 ? "#16a34a" : score >= 50 ? "#2563eb" : "#dc2626",
                          fontWeight: 600,
                        }}>
                          {score}%
                        </span>
                      )}
                      {isOptional && (
                        <span style={{
                          fontSize: "10px",
                          color: "#92400e",
                          background: "#fef3c7",
                          padding: "1px 6px",
                          borderRadius: "4px",
                          fontWeight: 600,
                        }}>
                          {t("subsectionNav.optional", "Optional")}
                        </span>
                      )}
                      {isReview && (
                        <span style={{
                          display: "inline-block",
                          padding: "1px 6px",
                          borderRadius: "4px",
                          fontSize: "11px",
                          fontWeight: 600,
                          backgroundColor: "#dbeafe",
                          color: "#1e40af",
                        }}>
                          {t("subsectionNav.review", "Review")}
                        </span>
                      )}
                      {isInfoPanel && (
                        <span style={{
                          display: "inline-block",
                          padding: "1px 6px",
                          borderRadius: "4px",
                          fontSize: "11px",
                          fontWeight: 600,
                          backgroundColor: "#f0fdf4",
                          color: "#15803d",
                        }}>
                          {t("subsectionNav.info", "Info")}
                        </span>
                      )}
                      {isLocked && (
                        <span style={{
                          fontSize: "11px",
                          color: "#64748b",
                          background: "#f1f5f9",
                          padding: "1px 6px",
                          borderRadius: "4px",
                        }}>
                          {t("subsectionNav.lockedSubsection", "Complete previous section first")}
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Start button */}
                  <button
                    disabled={loading || isLocked}
                    onClick={isLocked ? undefined : () =>
                      isInfoPanel
                        ? handleStartLearning(chunk.chunk_id)
                        : handleStartClick(chunk.chunk_id)
                    }
                    style={{
                      padding: "6px 16px",
                      borderRadius: "8px",
                      border: "none",
                      background: isExpanded ? "var(--color-border)" : "var(--color-primary)",
                      color: isExpanded ? "var(--color-text)" : "#fff",
                      fontSize: "13px",
                      fontWeight: 600,
                      cursor: loading || isLocked ? "not-allowed" : "pointer",
                      fontFamily: "inherit",
                      opacity: loading || isLocked ? 0.5 : 1,
                      flexShrink: 0,
                    }}
                  >
                    {isExpanded
                      ? t("common.cancel", "Cancel")
                      : t("learning.startSubsection", "Start")}
                  </button>
                </div>

                {/* Inline config panel */}
                {isExpanded && !isInfoPanel && (
                  <div style={{
                    padding: "12px 16px 16px",
                    borderTop: "1px solid var(--color-border)",
                    background: "color-mix(in srgb, var(--color-primary) 4%, var(--color-surface))",
                  }}>
                    {/* Style selector */}
                    <div style={{ marginBottom: "10px" }}>
                      <label style={{
                        display: "block",
                        fontSize: "12px",
                        fontWeight: 600,
                        color: "var(--color-text-muted)",
                        marginBottom: "4px",
                      }}>
                        {t("customize.style", "Style")}
                      </label>
                      <select
                        value={chunkStyle}
                        onChange={(e) => setChunkStyle(e.target.value)}
                        style={{
                          fontSize: "13px",
                          padding: "5px 8px",
                          borderRadius: "6px",
                          border: "1px solid var(--color-border)",
                          background: "var(--color-surface)",
                          color: "var(--color-text)",
                          fontFamily: "inherit",
                          cursor: "pointer",
                        }}
                      >
                        <option value="default">{t("customize.styleDefault", "Default")}</option>
                        <option value="pirate">{t("customize.stylePirate", "Pirate")}</option>
                        <option value="astronaut">{t("customize.styleAstronaut", "Astronaut")}</option>
                        <option value="gamer">{t("customize.styleGamer", "Gamer")}</option>
                      </select>
                    </div>

                    {/* Interests tag-input */}
                    <div style={{ marginBottom: "12px" }}>
                      <label style={{
                        display: "block",
                        fontSize: "12px",
                        fontWeight: 600,
                        color: "var(--color-text-muted)",
                        marginBottom: "4px",
                      }}>
                        {t("customize.interests", "Interests")}
                      </label>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: "4px", marginBottom: "6px" }}>
                        {chunkInterests.map((interest, i) => (
                          <span key={i} style={{
                            background: "color-mix(in srgb, var(--color-primary) 15%, var(--color-surface))",
                            color: "var(--color-primary)",
                            borderRadius: "4px",
                            padding: "2px 8px",
                            fontSize: "12px",
                            fontWeight: 500,
                            display: "flex",
                            alignItems: "center",
                            gap: "4px",
                          }}>
                            {interest}
                            <button
                              onClick={() => setChunkInterests(chunkInterests.filter((_, j) => j !== i))}
                              style={{
                                background: "none",
                                border: "none",
                                cursor: "pointer",
                                fontSize: "12px",
                                color: "var(--color-text-muted)",
                                padding: 0,
                                lineHeight: 1,
                              }}
                            >
                              ×
                            </button>
                          </span>
                        ))}
                      </div>
                      <input
                        value={chunkInterestInput}
                        onChange={(e) => setChunkInterestInput(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && chunkInterestInput.trim()) {
                            setChunkInterests([...chunkInterests, chunkInterestInput.trim()].slice(0, 10));
                            setChunkInterestInput("");
                          }
                        }}
                        placeholder={t("customize.addInterest", "Add topic (press Enter)")}
                        style={{
                          fontSize: "13px",
                          padding: "5px 8px",
                          borderRadius: "6px",
                          border: "1px solid var(--color-border)",
                          background: "var(--color-surface)",
                          color: "var(--color-text)",
                          fontFamily: "inherit",
                          width: "100%",
                          boxSizing: "border-box",
                        }}
                      />
                    </div>

                    {/* Start Learning button */}
                    <button
                      disabled={loading}
                      onClick={() => handleStartLearning(chunk.chunk_id)}
                      style={{
                        width: "100%",
                        padding: "9px 16px",
                        borderRadius: "8px",
                        border: "none",
                        background: "var(--color-primary)",
                        color: "#fff",
                        fontSize: "14px",
                        fontWeight: 700,
                        cursor: loading ? "not-allowed" : "pointer",
                        fontFamily: "inherit",
                        opacity: loading ? 0.6 : 1,
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        gap: "8px",
                      }}
                    >
                      {loading ? (
                        <>
                          <span style={{
                            width: "14px", height: "14px", borderRadius: "50%",
                            border: "2px solid rgba(255,255,255,0.3)",
                            borderTopColor: "#fff",
                            display: "inline-block",
                            animation: "spin 0.7s linear infinite",
                          }} />
                          {t("learning.startLearning", "Start Learning")}
                        </>
                      ) : (
                        t("learning.startLearning", "Start Learning")
                      )}
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
            <button
              onClick={() => {
                setChunkAnswers({});
                dispatch({ type: "RETURN_TO_PICKER" });
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
              {t("chunkQuestions.restudy", "Re-study")}
            </button>
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
      maxWidth: "800px",
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
      {phase === "CARDS" && (
        <div>
          {chunkList?.length > 0 && (
            <div style={{ marginBottom: "0.75rem" }}>
              <button
                onClick={() => dispatch({ type: "RETURN_TO_PICKER" })}
                style={{
                  background: "none", border: "none", cursor: "pointer",
                  color: "var(--color-primary, #7c3aed)", fontSize: "0.875rem",
                  padding: "0.25rem 0.5rem", display: "flex", alignItems: "center", gap: "0.25rem",
                }}
              >
                ← {t("nav.backToSubsections", "Back to subsections")}
              </button>
            </div>
          )}
          <CardLearningView />
        </div>
      )}
      {phase === "CHECKING" && <SocraticChat />}
      {phase === "COMPLETED" && <CompletionView />}

      {/* Remediation phases — cards with remediation banner */}
      {(phase === "REMEDIATING" || phase === "REMEDIATING_2") && (
        <div>
          {chunkList?.length > 0 && (
            <div style={{ marginBottom: "0.75rem" }}>
              <button
                onClick={() => dispatch({ type: "RETURN_TO_PICKER" })}
                style={{
                  background: "none", border: "none", cursor: "pointer",
                  color: "var(--color-primary, #7c3aed)", fontSize: "0.875rem",
                  padding: "0.25rem 0.5rem", display: "flex", alignItems: "center", gap: "0.25rem",
                }}
              >
                ← {t("nav.backToSubsections", "Back to subsections")}
              </button>
            </div>
          )}
          <CardLearningView remediationMode={true} />
        </div>
      )}

      {/* Re-check phases — Socratic chat with recheck banner */}
      {(phase === "RECHECKING" || phase === "RECHECKING_2") && (
        <SocraticChat recheckMode={true} />
      )}
    </div>
  );
}
