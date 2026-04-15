import { Fragment, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams, useNavigate, useSearchParams } from "react-router-dom";
import { useSession } from "../context/SessionContext";
import { useStudent } from "../context/StudentContext";
import { useTheme } from "../context/ThemeContext";
import ProgressBar from "../components/learning/ProgressBar";
import VerticalProgressRail from "../components/learning/VerticalProgressRail";
import CardLearningView from "../components/learning/CardLearningView";
import CompletionView from "../components/learning/CompletionView";
import { trackEvent } from "../utils/analytics";
import { AlertCircle, LogOut } from "lucide-react";
import { checkConceptReadiness } from "../api/concepts";
import { getSession, getChunkList } from "../api/sessions";
import { ProgressRing } from "../components/ui";

export default function LearningPage() {
  const { t } = useTranslation();
  const { conceptId } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const bookSlug = searchParams.get("book_slug") || "prealgebra";
  const {
    phase, startLesson, error, reset,
    session, conceptTitle, bookTitle, currentCardIndex,
    cards, cardAnswers, messages,
    chunkList, chunkProgress, currentChunkId, currentChunkMode,
    allStudyComplete, submitChunkAnswers, chunkQuestions, chunkEvalResult,
    startChunk, dispatch, loading,
  } = useSession();
  const { student } = useStudent();
  const { style: globalStyle } = useTheme();

  const [prereqWarning, setPrereqWarning] = useState(null);
  const [prereqChecked, setPrereqChecked] = useState(false);
  const [chunkAnswers, setChunkAnswers] = useState({});

  // Per-chunk picker state
  const [selectedChunkId, setSelectedChunkId] = useState(null);
  const [chunkStyle, setChunkStyle] = useState(globalStyle || "default");
  const [chunkInterests, setChunkInterests] = useState([]);
  const [chunkInterestInput, setChunkInterestInput] = useState("");

  useEffect(() => {
    if (conceptId && phase === "IDLE" && !prereqChecked) {
      setPrereqChecked(true);
      const decodedConceptId = decodeURIComponent(conceptId);

      const launchLesson = () => startLesson(decodedConceptId, null, []);

      const tryResume = () => {
        const savedSessionId = localStorage.getItem(`ada_session_${student?.id}_${decodedConceptId}`);
        if (savedSessionId) {
          getSession(savedSessionId)
            .then(res => {
              const existing = res.data;
              if (existing && existing.phase !== "COMPLETED") {
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

      checkConceptReadiness(decodedConceptId, student.id, bookSlug)
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
  const [showBackConfirm, setShowBackConfirm] = useState(false);
  const [sharedCardStates, setSharedCardStates] = useState({});

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
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: "100vh", gap: "16px", padding: "32px" }}>
        <AlertCircle size={48} color="#EF4444" />
        <h2 style={{ color: "#EF4444", fontWeight: 700, margin: 0 }}>{t("common.error")}</h2>
        <p style={{ color: "#94A3B8", textAlign: "center", maxWidth: "400px", margin: 0 }}>
          {error}
        </p>
        <div style={{ display: "flex", gap: "12px" }}>
          <button
            onClick={() => {
              if (phase === "SELECTING_CHUNK") {
                dispatch({ type: "CLEAR_ERROR" });
              } else {
                reset();
                startLesson(decodeURIComponent(conceptId), null, []);
              }
            }}
            style={{ padding: "10px 24px", borderRadius: "10px", border: "none", background: "#EA580C", color: "#FFFFFF", fontSize: "16px", fontWeight: 600, cursor: "pointer", fontFamily: "inherit" }}
          >
            {t("learning.tryAgain")}
          </button>
          <button
            onClick={() => { reset(); navigate("/map"); }}
            style={{ padding: "10px 24px", borderRadius: "10px", border: "1.5px solid #F97316", background: "transparent", color: "#F97316", fontSize: "16px", fontWeight: 600, cursor: "pointer", fontFamily: "inherit" }}
          >
            {t("learning.backToMap")}
          </button>
        </div>
      </div>
    );
  }

  if (phase === "LOADING" || phase === "IDLE") {
    return (
      <div style={{ maxWidth: "1100px", margin: "0 auto", padding: "24px 24px 48px" }}>
        {/* Skeleton: mimics card layout */}
        <div style={{ display: "flex", gap: "16px", alignItems: "flex-start" }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            {/* Progress dots skeleton */}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "6px", marginBottom: "16px" }}>
              {[0, 1, 2, 3].map(i => (
                <div key={i} className="skeleton-shimmer" style={{ borderRadius: "9999px", height: "12px", width: i === 0 ? "28px" : "12px" }} />
              ))}
            </div>
            {/* Card skeleton */}
            <div style={{ background: "var(--color-surface)", borderRadius: "var(--radius-lg)", border: "2px solid var(--color-border)", overflow: "hidden" }}>
              {/* Card header skeleton */}
              <div className="skeleton-shimmer" style={{ height: "64px", borderRadius: 0 }} />
              {/* Card body skeleton */}
              <div style={{ padding: "24px 28px" }}>
                <div className="skeleton-shimmer" style={{ height: "16px", marginBottom: "10px" }} />
                <div className="skeleton-shimmer" style={{ height: "16px", width: "90%", marginBottom: "10px" }} />
                <div className="skeleton-shimmer" style={{ height: "16px", width: "75%", marginBottom: "24px" }} />
                <div className="skeleton-shimmer" style={{ height: "44px", marginBottom: "8px", borderRadius: "9999px" }} />
                <div className="skeleton-shimmer" style={{ height: "44px", marginBottom: "8px", borderRadius: "9999px" }} />
                <div className="skeleton-shimmer" style={{ height: "44px", borderRadius: "9999px" }} />
              </div>
            </div>
          </div>
          {/* Assistant panel skeleton */}
          <div style={{ width: "320px", flexShrink: 0 }}>
            <div className="skeleton-shimmer" style={{ height: "400px", borderRadius: "var(--radius-lg)" }} />
          </div>
        </div>
        <p style={{ textAlign: "center", color: "var(--color-text-muted)", marginTop: "24px", fontSize: "0.95rem", fontWeight: 600 }}>
          {t("learning.craftingCards")}
        </p>
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
        setChunkStyle(globalStyle || "default");
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

    const firstExerciseIdx = visibleChunks.findIndex(
      (c) => c.chunk_type === "exercise" && !c.is_optional
    );

    const modeBadgeLabel = (mode) => t(`learning.mode.${mode}`, mode);

    const completedCount = chunkProgress ? Object.keys(chunkProgress).length : 0;
    const totalChunks = visibleChunks.length;
    const progressPct = totalChunks > 0 ? Math.round((completedCount / totalChunks) * 100) : 0;
    const lockedCount = visibleChunks.filter((c, idx) => {
      const isGate = c.chunk_type === "exercise_gate";
      const isInfo = c.chunk_type === "learning_objective";
      if (isGate) return !(allStudyComplete === true);
      if (isInfo) return false;
      const prev = visibleChunks.slice(0, idx).filter(p => p.chunk_type !== "learning_objective" && !p.is_optional);
      return prev.length > 0 && !(prev[prev.length - 1]?.chunk_id in (chunkProgress || {}));
    }).length;
    const availableCount = totalChunks - completedCount - lockedCount;

    return (
      <div style={{ display: "flex", gap: "24px", padding: "24px 24px 64px" }}>
        {/* Prerequisite Warning Modal */}
        {prereqWarning && (
          <div style={{ position: "fixed", inset: 0, zIndex: 1000, background: "rgba(0,0,0,0.6)", backdropFilter: "blur(4px)", display: "flex", alignItems: "center", justifyContent: "center", padding: "16px" }}>
            <div style={{ background: "var(--color-surface)", borderRadius: "var(--radius-xl)", padding: "32px", maxWidth: "480px", width: "100%", boxShadow: "0 24px 64px rgba(0,0,0,0.4)", border: "1px solid var(--color-border)", display: "flex", flexDirection: "column", gap: "16px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                <AlertCircle size={28} color="#EF4444" style={{ flexShrink: 0 }} />
                <h2 style={{ margin: 0, fontSize: "1.25rem", fontWeight: 800, color: "var(--color-text)", lineHeight: 1.3 }}>
                  {t("learning.notReadyYet")}
                </h2>
              </div>
              <p style={{ margin: 0, fontSize: "0.95rem", color: "#94A3B8", lineHeight: 1.6 }}>
                {t("learning.helpsMasterFirst")}
              </p>
              <ul style={{ margin: 0, paddingInlineStart: "20px", display: "flex", flexDirection: "column", gap: "4px" }}>
                {prereqWarning.unmet.map((prereq) => (
                  <li key={prereq.concept_id} style={{ fontSize: "0.95rem", color: "var(--color-text)", fontWeight: 600, lineHeight: 1.4 }}>
                    {prereq.concept_title}
                  </li>
                ))}
              </ul>
              <div style={{ display: "flex", gap: "12px", marginTop: "8px", flexWrap: "wrap" }}>
                <button onClick={() => { setPrereqWarning(null); navigate("/map"); }}
                  style={{ flex: "1 1 auto", padding: "10px 20px", borderRadius: "var(--radius-md)", border: "none", background: "#EA580C", color: "#FFFFFF", fontSize: "0.95rem", fontWeight: 700, cursor: "pointer", fontFamily: "inherit" }}>
                  {t("learning.learnPrereqFirst")}
                </button>
                <button onClick={() => { setPrereqWarning(null); startLesson(decodeURIComponent(conceptId), null, []); }}
                  style={{ flex: "1 1 auto", padding: "10px 20px", borderRadius: "var(--radius-md)", border: "1px solid var(--color-border)", background: "transparent", color: "#94A3B8", fontSize: "0.95rem", fontWeight: 600, cursor: "pointer", fontFamily: "inherit" }}>
                  {t("learning.startAnyway")}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Left column */}
        <div style={{ flex: 1, minWidth: 0 }}>

        {/* Hero header */}
        {(() => {
          const decodedId = decodeURIComponent(conceptId);
          const sm = decodedId.match(/(\d+)\.(\d+)/);
          const chNum = sm ? sm[1] : "";
          const secNum = sm ? `${sm[1]}.${sm[2]}` : "";
          return (
            <div style={{
              marginBottom: "24px", padding: "28px 24px",
              background: "linear-gradient(135deg, #FFF7ED 0%, #FFEDD5 50%, #FFF7ED 100%)",
              borderRadius: "20px", border: "1px solid rgba(249,115,22,0.12)",
            }}>
              <h1 style={{ margin: 0, fontSize: "24px", fontWeight: 800, color: "#0f172a", fontFamily: "'Outfit', sans-serif", lineHeight: 1.3 }}>
                {conceptTitle || decodedId.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())}
              </h1>
              <p style={{ margin: "6px 0 0", fontSize: "13px", color: "#78716c", fontWeight: 500 }}>
                {chNum && t("learning.chapterLabel", { num: chNum })}{secNum && ` · ${t("learning.sectionLabel", { num: secNum })}`}{(bookTitle || bookSlug) && ` · ${bookTitle || bookSlug.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())}`}
              </p>
              <span style={{
                display: "inline-block", marginTop: "12px", padding: "5px 14px",
                borderRadius: "9999px", fontSize: "12px", fontWeight: 700,
                color: "#EA580C", background: "rgba(249,115,22,0.1)",
                border: "1px solid rgba(249,115,22,0.2)",
              }}>
                📚 {t("sidebar.subsectionsSummary", { count: totalChunks, minutes: totalChunks * 5 })}
              </span>
            </div>
          );
        })()}

        {/* Section label */}
        <div style={{ marginBottom: "14px", fontSize: "15px", fontWeight: 700, color: "#0f172a" }}>
          {t("sidebar.subsections")} <span style={{ fontWeight: 400, color: "#94a3b8", fontSize: "13px" }}>· {t("sidebar.chooseToStart")}</span>
        </div>

        {visibleChunks.length === 0 && (
          <div style={{ textAlign: "center", padding: "32px 16px", color: "#94A3B8", fontSize: "0.95rem", fontWeight: 500 }}>
            {t("chunk.noSections", "No sections available for this concept.")}
          </div>
        )}

        <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
          {visibleChunks.map((chunk, idx) => {
            const isGate = chunk.chunk_type === "exercise_gate";
            const isOptional = chunk.is_optional === true;
            const isInfoPanel = chunk.chunk_type === "learning_objective";
            const isReview = chunk.chunk_type === "chapter_review";
            const isExpanded = selectedChunkId === chunk.chunk_id;
            const prevRequired = visibleChunks.slice(0, idx).filter(
              (c) => c.chunk_type !== "learning_objective" && !c.is_optional
            );

            // Gate is locked until ALL non-gate, non-optional, non-info study chunks are complete
            const isLocked = isGate
              ? !(allStudyComplete === true)
              : !isInfoPanel
                  && prevRequired.length > 0
                  && !(prevRequired[prevRequired.length - 1]?.chunk_id in (chunkProgress || {}));

            // Gate completion is driven by backend concept_mastered flag
            const isDone = isGate
              ? chunk.completed === true
              : chunk.chunk_id in (chunkProgress || {});

            const score = isGate ? null : chunkProgress?.[chunk.chunk_id]?.score;

            const statusColor = isDone
              ? "#22C55E"
              : isLocked
                ? "#94A3B8"
                : "#F97316";

            const statusIcon = isDone
              ? "✓"
              : isLocked
                ? "🔒"
                : isGate
                  ? "★"
                  : `${idx + 1}`;

            return (
              <Fragment key={chunk.chunk_id}>
                {idx === firstExerciseIdx && firstExerciseIdx > 0 && (
                  <div style={{ paddingTop: "10px", paddingBottom: "6px", paddingLeft: "4px", marginTop: "2px", fontSize: "11px", fontWeight: 600, letterSpacing: "0.08em", textTransform: "uppercase", color: "#94A3B8", borderTop: "1px solid rgba(128,128,128,0.2)" }}>
                    {t("chunks.exerciseSection", "Exercise Practice")}
                  </div>
                )}
              <div
                style={{
                  borderRadius: "16px",
                  border: isExpanded
                    ? "2px solid #F97316"
                    : isDone
                      ? "1.5px solid rgba(74,222,128,0.25)"
                      : "1.5px solid #e2e8f0",
                  background: isExpanded
                    ? "#FFF7ED"
                    : isDone
                      ? "rgba(240,253,244,0.5)"
                      : "#ffffff",
                  overflow: "hidden",
                  transition: "all 0.15s",
                  boxShadow: isExpanded
                    ? "0 4px 20px rgba(249,115,22,0.15)"
                    : "0 1px 4px rgba(0,0,0,0.04)",
                  padding: isExpanded ? "4px" : "0",
                }}
                onMouseEnter={(e) => { if (!isExpanded) e.currentTarget.style.boxShadow = "0 4px 12px rgba(0,0,0,0.08)"; }}
                onMouseLeave={(e) => { if (!isExpanded) e.currentTarget.style.boxShadow = "0 1px 4px rgba(0,0,0,0.04)"; }}
              >
                {/* Main row */}
                <div style={{ display: "flex", alignItems: "center", gap: "14px", padding: "14px 20px" }}>
                  {/* Number/status circle */}
                  <div style={{
                    width: "44px",
                    height: "44px",
                    borderRadius: "50%",
                    flexShrink: 0,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: isDone ? "18px" : "15px",
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
                    <div style={{ fontSize: "14px", lineHeight: 1.4, marginBottom: "2px", fontWeight: isDone ? 500 : 600, color: isLocked ? "#94A3B8" : "#0F172A" }}>
                      {chunk.heading}
                    </div>
                    <div style={{ display: "flex", gap: "6px", flexWrap: "wrap", alignItems: "center" }}>
                      {isDone && score != null && (
                        <span style={{ fontSize: "11px", fontWeight: 700, color: score >= 80 ? "#22C55E" : score >= 50 ? "#F97316" : "#EF4444" }}>
                          {score}% score
                        </span>
                      )}
                      {isDone && chunkProgress?.[chunk.chunk_id]?.mode_used && (
                        <span style={{ fontSize: "11px", fontWeight: 600, padding: "3px 10px", borderRadius: "6px", background: "#F8FAFC", color: "#64748B", border: "1px solid #E2E8F0" }}>
                          {modeBadgeLabel(chunkProgress[chunk.chunk_id].mode_used)}
                        </span>
                      )}
                      {!isDone && !isInfoPanel && chunk.chunk_type !== "exercise_gate" && idx === firstUncompletedIdx && currentChunkMode && (
                        <span style={{
                          fontSize: "11px", fontWeight: 600, padding: "3px 10px",
                          borderRadius: "6px", background: "#FFF7ED",
                          color: "#EA580C", border: "1px solid rgba(249,115,22,0.25)",
                        }}>
                          {modeBadgeLabel(currentChunkMode)} mode
                        </span>
                      )}
                      {isOptional && (
                        <span style={{ fontSize: "11px", fontWeight: 600, padding: "3px 10px", borderRadius: "6px", background: "#FFFBEB", color: "#D97706", border: "1px solid rgba(217,119,6,0.2)" }}>
                          {t("subsectionNav.optional", "Optional")}
                        </span>
                      )}
                      {chunk.exam_disabled && !isGate && !isInfoPanel && (
                        <span style={{ fontSize: "11px", fontWeight: 500, padding: "3px 8px", borderRadius: "6px", background: "#FAF5FF", color: "#9333EA", border: "1px solid rgba(147,51,234,0.2)" }}>
                          {t("subsectionNav.noExam", "No exam")}
                        </span>
                      )}
                      {isReview && (
                        <span style={{ fontSize: "11px", fontWeight: 600, padding: "3px 10px", borderRadius: "6px", background: "#EFF6FF", color: "#2563EB", border: "1px solid rgba(37,99,235,0.2)" }}>
                          {t("subsectionNav.review", "Review")}
                        </span>
                      )}
                      {isInfoPanel && (
                        <span style={{ fontSize: "11px", fontWeight: 600, padding: "3px 10px", borderRadius: "6px", background: "#F0FDF4", color: "#16A34A", border: "1px solid rgba(22,163,74,0.2)" }}>
                          {t("subsectionNav.info", "Info")}
                        </span>
                      )}
                      {isGate && (
                        <span style={{ fontSize: "11px", fontWeight: 700, padding: "3px 10px", borderRadius: "6px", background: "#FAF5FF", color: "#7C3AED", border: "1px solid rgba(124,58,237,0.2)" }}>
                          {t("subsectionNav.exam", "Exam")}
                        </span>
                      )}
                      {isLocked && isGate && (
                        <span style={{ fontSize: "11px", fontWeight: 500, color: "#94a3b8" }}>
                          {t("exam.locked", "Complete all sections first")}
                        </span>
                      )}
                      {isLocked && !isGate && (
                        <span style={{ fontSize: "11px", fontWeight: 500, color: "#94a3b8" }}>
                          {t("subsectionNav.lockedSubsection", "Complete previous section first")}
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Action button */}
                  {!isLocked && !isGate && (
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
                        ? t("map.reviewLesson", "Review")
                        : isExpanded
                          ? "▲"
                          : t("learning.startSubsection", "Start")
                      }
                    </button>
                  )}
                  {isLocked && (
                    <div style={{ width: "34px", height: "34px", flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center", opacity: 0.35 }}>
                      🔒
                    </div>
                  )}
                </div>

                {/* Expanded customization panel */}
                {isExpanded && (
                  <div style={{
                    margin: "0 16px 16px",
                    padding: "18px 20px",
                    borderRadius: "12px",
                    background: "#ffffff",
                    border: "1px solid #f1f5f9",
                    display: "flex", flexDirection: "column", gap: "16px",
                  }}>
                    {/* Style picker */}
                    <div>
                      <div style={{ fontSize: "11px", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: "#94A3B8", marginBottom: "8px" }}>
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
                      <div style={{ fontSize: "11px", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: "#94A3B8", marginBottom: "8px" }}>
                        {t("customize.interests", "Interests")} <span style={{ fontWeight: 400, textTransform: "none", letterSpacing: "normal" }}>({t("customize.interestsHint", "optional — makes examples fun")})</span>
                      </div>
                      {/* Preset interest chips */}
                      <div style={{ display: "flex", gap: "6px", flexWrap: "wrap", marginBottom: "8px" }}>
                        {[
                          { id: "Sports", emoji: "⚽" },
                          { id: "Gaming", emoji: "🎮" },
                          { id: "Music", emoji: "🎵" },
                          { id: "Movies", emoji: "🎬" },
                          { id: "Food", emoji: "🍕" },
                          { id: "Animals", emoji: "🐾" },
                          { id: "Space", emoji: "🚀" },
                          { id: "Technology", emoji: "💻" },
                          { id: "Art", emoji: "🎨" },
                          { id: "Nature", emoji: "🌿" },
                        ].map(({ id, emoji }) => {
                          const selected = chunkInterests.includes(id);
                          return (
                            <button
                              key={id}
                              onClick={() => setChunkInterests((prev) =>
                                selected ? prev.filter((i) => i !== id) : [...new Set([...prev, id])]
                              )}
                              style={{
                                padding: "4px 10px",
                                borderRadius: "9999px",
                                border: selected
                                  ? "2px solid var(--color-primary)"
                                  : "1.5px solid var(--color-border-strong, var(--color-border))",
                                background: selected ? "var(--color-primary-light)" : "transparent",
                                color: selected ? "var(--color-primary)" : "var(--color-text-muted)",
                                fontSize: "12px", fontWeight: 600,
                                cursor: "pointer", fontFamily: "inherit",
                                transition: "all 0.15s",
                              }}
                            >
                              {emoji} {id}
                            </button>
                          );
                        })}
                      </div>
                      <div style={{ display: "flex", gap: "8px", flexWrap: "wrap", marginBottom: chunkInterests.length > 0 ? "8px" : "0" }}>
                        {chunkInterests.map((interest) => (
                          <span
                            key={interest}
                            onClick={() => setChunkInterests((prev) => prev.filter((i) => i !== interest))}
                            style={{ padding: "4px 10px", borderRadius: "9999px", background: "var(--color-primary-light)", color: "var(--color-primary)", fontSize: "12px", fontWeight: 600, cursor: "pointer", border: "1px solid rgba(99,102,241,0.3)" }}
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
                        style={{ width: "100%", padding: "8px 12px", borderRadius: "10px", border: "1.5px solid var(--color-border-strong, var(--color-border))", background: "var(--color-surface)", color: "var(--color-text)", fontSize: "13px", fontFamily: "inherit", outline: "none", boxSizing: "border-box" }}
                      />
                    </div>

                    {/* Start button */}
                    <button
                      onClick={() => handleStartLearning(chunk.chunk_id)}
                      disabled={loading}
                      style={{
                        padding: "14px",
                        borderRadius: "14px",
                        border: "none",
                        background: "linear-gradient(135deg, #F97316, #EA580C)",
                        color: "#fff",
                        fontSize: "15px",
                        fontWeight: 700,
                        cursor: loading ? "not-allowed" : "pointer",
                        fontFamily: "inherit",
                        opacity: loading ? 0.7 : 1,
                        boxShadow: "0 4px 16px rgba(249,115,22,0.3)",
                        transition: "opacity 0.15s",
                        margin: "0 16px 16px",
                      }}
                    >
                      {loading ? t("learning.gettingReady", "Getting ready...") : `▶  ${t("learning.startLearning", "Start Learning")}`}
                    </button>
                  </div>
                )}
              </div>
              </Fragment>
            );
          })}
        </div>
        </div>{/* end left column */}

        {/* Right column — Concept overview */}
        <div style={{ width: "280px", flexShrink: 0, position: "sticky", top: "24px", alignSelf: "flex-start" }}>
          <div style={{ background: "#fff", borderRadius: "16px", border: "1px solid #e2e8f0", padding: "24px" }}>
            <h3 style={{ margin: "0 0 16px", fontSize: "16px", fontWeight: 700, color: "#0f172a", fontFamily: "'Outfit', sans-serif" }}>
              {t("sidebar.conceptOverview")}
            </h3>

            {/* Progress ring */}
            <div style={{ display: "flex", justifyContent: "center", marginBottom: "20px" }}>
              <ProgressRing score={progressPct} size="sm" />
            </div>

            {/* Stats grid */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px", marginBottom: "20px" }}>
              {[
                { id: "completed", value: completedCount, label: t("sidebar.completed"), color: "#22C55E" },
                { id: "available", value: availableCount, label: t("sidebar.available"), color: "#3B82F6" },
                { id: "locked", value: lockedCount, label: t("sidebar.locked"), color: "#94a3b8" },
                { id: "estTime", value: `~${totalChunks * 5}m`, label: t("sidebar.estTime"), color: "#8B5CF6" },
              ].map(({ id, value, label, color }) => (
                <div key={id} style={{ textAlign: "center", padding: "10px 8px", borderRadius: "12px", border: "1px solid #f1f5f9" }}>
                  <div style={{ fontSize: "20px", fontWeight: 800, color, fontFamily: "'Outfit', sans-serif" }}>{value}</div>
                  <div style={{ fontSize: "11px", color: "#94a3b8", fontWeight: 500, marginTop: "2px" }}>{label}</div>
                </div>
              ))}
            </div>

            {/* Prerequisites */}
            <div style={{ marginBottom: "16px", padding: "12px", borderRadius: "12px", background: "#f8fafc" }}>
              <div style={{ fontSize: "11px", fontWeight: 700, color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: "6px" }}>
                {t("sidebar.prerequisites")}
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "13px", color: "#334155" }}>
                <span style={{ width: 8, height: 8, borderRadius: "50%", background: "#22C55E", display: "inline-block" }} />
                {t("sidebar.noPrerequisites")}
              </div>
            </div>

            {/* Rewards */}
            <div style={{ marginBottom: "16px", padding: "12px", borderRadius: "12px", background: "#f8fafc" }}>
              <div style={{ fontSize: "11px", fontWeight: 700, color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: "6px" }}>
                {t("sidebar.rewards")}
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "13px", color: "#334155" }}>
                <span style={{ fontSize: "16px" }}>⭐</span>
                {t("sidebar.xpOnMastery")}
              </div>
            </div>

            {/* Study tip */}
            <div style={{ padding: "14px", borderRadius: "12px", background: "linear-gradient(135deg, #fff7ed, #ffedd5)" }}>
              <div style={{ fontSize: "13px", fontWeight: 700, color: "#92400e", marginBottom: "4px" }}>
                💡 {t("sidebar.studyTip")}
              </div>
              <div style={{ fontSize: "12px", color: "#78350f", lineHeight: 1.5 }}>
                {t("sidebar.studyTipText")}
              </div>
            </div>
          </div>
        </div>

      </div>
    );
  }

  // ── Per-chunk typed Q&A ────────────────────────────────────────────────────
  if (phase === "CHUNK_QUESTIONS") {
    const evalResult = chunkEvalResult;
    const allAnswered = chunkQuestions.every((_, i) => (chunkAnswers[i] || "").trim().length > 0);

    return (
      <div style={{ maxWidth: "700px", margin: "0 auto", padding: "32px 24px 48px" }}>
        {!evalResult && (
          <div style={{ marginBottom: "20px" }}>
            <button
              onClick={() => dispatch({ type: "RETURN_TO_PICKER" })}
              style={{ background: "none", border: "none", cursor: "pointer", color: "#94A3B8", fontSize: "14px", padding: "4px 0", display: "flex", alignItems: "center", gap: "4px" }}
            >
              ← {t("nav.backToSubsections", "Back to subsections")}
            </button>
          </div>
        )}
        <h2 style={{ fontWeight: 800, fontSize: "1.3rem", color: "var(--color-text)", marginBottom: "4px", marginTop: 0 }}>
          {t("chunkQuestions.title", "Knowledge Check")}
        </h2>
        <p style={{ color: "#94A3B8", fontSize: "0.9rem", marginBottom: "24px", marginTop: 0 }}>
          {t("chunkQuestions.instruction", "Answer in your own words — no need to be exact.")}
        </p>

        {!evalResult && chunkQuestions.map((q, i) => (
          <div key={q.index} style={{ marginBottom: "20px", padding: "16px 20px", borderRadius: "10px", border: "1px solid #E2E8F0", background: "#FFFFFF" }}>
            <p style={{ fontWeight: 700, fontSize: "16px", color: "var(--color-text)", marginBottom: "8px", marginTop: 0, lineHeight: 1.5 }}>
              Q{i + 1}. {q.text}
            </p>
            <textarea
              value={chunkAnswers[i] || ""}
              onChange={(e) => setChunkAnswers((prev) => ({ ...prev, [i]: e.target.value }))}
              placeholder={t("chunkQuestions.placeholder", "Type your answer here...")}
              rows={3}
              style={{ width: "100%", borderRadius: "8px", padding: "12px", fontSize: "0.95rem", border: "2px solid #E2E8F0", background: "var(--color-surface)", color: "var(--color-text)", fontFamily: "inherit", boxSizing: "border-box", resize: "vertical" }}
            />
          </div>
        ))}

        {evalResult && (
          <div style={{ padding: "20px", borderRadius: "12px", marginBottom: "24px", border: "1.5px solid", borderColor: evalResult.passed ? "rgba(22,163,74,0.3)" : "rgba(239,68,68,0.3)", background: evalResult.passed ? "rgba(22,163,74,0.07)" : "rgba(239,68,68,0.07)" }}>
            <div style={{ fontSize: "1.3rem", fontWeight: 800, marginBottom: "4px", color: evalResult.passed ? "#16A34A" : "#DC2626" }}>
              {evalResult.passed
                ? `✓ ${t("chunkQuestions.passed", "Passed")} ${Math.round(evalResult.score * 100)}%`
                : `✗ ${Math.round(evalResult.score * 100)}% — ${t("chunkQuestions.failed", "Not quite — let's review")}`}
            </div>
            {evalResult.passed && (
              <p style={{ color: "#94A3B8", fontSize: "0.9rem", margin: 0 }}>
                {evalResult.all_study_complete
                  ? t("chunkQuestions.completing", "Completing concept...")
                  : t("chunkQuestions.continuing", "Continuing...")}
              </p>
            )}
            {!evalResult.passed && evalResult.feedback?.length > 0 && (
              <div style={{ marginTop: "16px" }}>
                {evalResult.feedback.map((fb, i) => (
                  <div key={i} style={{ marginBottom: "12px", padding: "10px 14px", borderRadius: "8px", border: "1px solid", borderColor: fb.correct ? "rgba(22,163,74,0.2)" : "rgba(239,68,68,0.2)", background: fb.correct ? "rgba(22,163,74,0.04)" : "rgba(239,68,68,0.04)" }}>
                    <span style={{ fontWeight: 700, marginRight: "6px", color: fb.correct ? "#16A34A" : "#DC2626" }}>
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

        <div style={{ display: "flex", gap: "12px", justifyContent: "flex-end", flexWrap: "wrap" }}>
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
              style={{ padding: "12px 32px", borderRadius: "10px", border: "none", fontWeight: 700, fontSize: "16px", fontFamily: "inherit", background: allAnswered && !loading ? "#EA580C" : "#E2E8F0", color: allAnswered && !loading ? "#FFFFFF" : "#94A3B8", cursor: allAnswered && !loading ? "pointer" : "not-allowed" }}
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
                style={{ padding: "12px 28px", borderRadius: "10px", border: "1.5px solid #E2E8F0", background: "transparent", color: "#94A3B8", fontWeight: 600, fontSize: "16px", cursor: "pointer", fontFamily: "inherit" }}
              >
                ← {t("nav.backToSubsections", "Back to subsection list")}
              </button>
              <button
                onClick={() => {
                  setChunkAnswers({});
                  startChunk(currentChunkId, currentChunkMode);
                }}
                style={{ padding: "12px 28px", borderRadius: "10px", border: "none", background: "#F97316", color: "#FFFFFF", fontWeight: 700, fontSize: "16px", cursor: "pointer", fontFamily: "inherit" }}
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
  const isCardPhase = phase === "CARDS";
  const isChatPhase = phase === "CHUNK_QUESTIONS";

  return (
    <div style={{ margin: "0 auto", padding: "24px 24px 48px", maxWidth: isCardPhase ? "100%" : "900px" }}>
      {/* ── Prerequisite Warning Modal ── */}
      {prereqWarning && (
        <div style={{ position: "fixed", inset: 0, zIndex: 1000, backgroundColor: "rgba(0,0,0,0.55)", display: "flex", alignItems: "center", justifyContent: "center", padding: "16px" }}>
          <div style={{ backgroundColor: "#FFFFFF", borderRadius: "16px", padding: "32px", maxWidth: "480px", width: "100%", boxShadow: "0 20px 60px rgba(0,0,0,0.3)", display: "flex", flexDirection: "column", gap: "16px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
              <AlertCircle size={28} color="#EF4444" style={{ flexShrink: 0 }} />
              <h2 style={{ margin: 0, fontSize: "20px", fontWeight: 800, color: "#0F172A", lineHeight: 1.2 }}>
                {t("learning.notReadyYet")}
              </h2>
            </div>
            <p style={{ margin: 0, fontSize: "15px", color: "#64748B", lineHeight: 1.5 }}>
              {t("learning.helpsMasterFirst")}
            </p>
            <ul style={{ margin: 0, paddingLeft: "20px", display: "flex", flexDirection: "column", gap: "4px" }}>
              {prereqWarning.unmet.map((prereq) => (
                <li key={prereq.concept_id} style={{ fontSize: "15px", color: "#0F172A", fontWeight: 600 }}>
                  {prereq.concept_title}
                </li>
              ))}
            </ul>
            <div style={{ display: "flex", gap: "12px", marginTop: "8px", flexWrap: "wrap" }}>
              <button
                onClick={() => { setPrereqWarning(null); navigate("/map"); }}
                style={{ flex: "1 1 auto", padding: "10px 20px", borderRadius: "8px", border: "none", backgroundColor: "#F97316", color: "#FFFFFF", fontSize: "15px", fontWeight: 700, cursor: "pointer" }}
              >
                {t("learning.learnPrereqFirst")}
              </button>
              <button
                onClick={() => { setPrereqWarning(null); startLesson(decodeURIComponent(conceptId), null, []); }}
                style={{ flex: "1 1 auto", padding: "10px 20px", borderRadius: "8px", border: "1px solid #E2E8F0", backgroundColor: "transparent", color: "#64748B", fontSize: "15px", fontWeight: 600, cursor: "pointer" }}
              >
                {t("learning.startAnyway")}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Exit bar (Socratic check phases only — cards phase uses "Back to subsections" instead) ── */}
      {isChatPhase && (
        <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", marginBottom: "12px", gap: "12px" }}>
          {showExitConfirm ? (
            <div style={{ display: "flex", alignItems: "center", gap: "12px", padding: "8px 16px", borderRadius: "10px", backgroundColor: "#FFFFFF", border: "2px solid #EF4444" }}>
              <span style={{ fontSize: "14px", color: "#0F172A", fontWeight: 600 }}>
                {t("learning.exitConfirm")}
              </span>
              <button
                onClick={handleExitConfirm}
                style={{ padding: "6px 14px", borderRadius: "8px", border: "none", backgroundColor: "#EF4444", color: "#FFFFFF", fontSize: "13px", fontWeight: 700, cursor: "pointer" }}
              >
                {t("learning.exitYes")}
              </button>
              <button
                onClick={() => setShowExitConfirm(false)}
                style={{ padding: "6px 14px", borderRadius: "8px", border: "1px solid #E2E8F0", backgroundColor: "transparent", color: "#64748B", fontSize: "13px", fontWeight: 600, cursor: "pointer" }}
              >
                {t("learning.exitNo")}
              </button>
            </div>
          ) : (
            <button
              onClick={() => setShowExitConfirm(true)}
              style={{ display: "flex", alignItems: "center", gap: "4px", padding: "6px 14px", borderRadius: "8px", border: "1px solid #E2E8F0", backgroundColor: "transparent", color: "#64748B", fontSize: "13px", fontWeight: 600, cursor: "pointer" }}
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
        <div style={{ display: "flex", gap: "12px", alignItems: "flex-start" }}>
          <VerticalProgressRail total={cards?.length ?? 0} current={currentCardIndex} cardStates={sharedCardStates} />
          <div style={{ flex: 1, minWidth: 0 }}>
            {chunkList?.length > 0 && (
              <div style={{ marginBottom: "12px" }}>
                <button
                  onClick={() => setShowBackConfirm(true)}
                  style={{ background: "none", border: "none", cursor: "pointer", color: "#F97316", fontSize: "14px", padding: "4px 8px", display: "flex", alignItems: "center", gap: "4px" }}
                >
                  ← {t("nav.backToSubsections", "Back to subsections")}
                </button>
              </div>
            )}
            <CardLearningView onCardStatesChange={setSharedCardStates} />
          </div>
        </div>
      )}
      {phase === "COMPLETED" && <CompletionView />}


      {/* Back to subsections confirmation modal */}
      {showBackConfirm && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="back-confirm-title"
          style={{ position: "fixed", inset: 0, zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center", backgroundColor: "rgba(0,0,0,0.5)" }}
          onClick={() => setShowBackConfirm(false)}
        >
          <div
            style={{ backgroundColor: "#FFFFFF", border: "1px solid #E2E8F0", borderRadius: "16px", padding: "24px", maxWidth: "400px", width: "90%", boxShadow: "0 8px 32px rgba(0,0,0,0.15)" }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "12px" }}>
              <AlertCircle size={22} color="#F59E0B" />
              <h2 id="back-confirm-title" style={{ margin: 0, fontSize: "16px", fontWeight: 700, color: "#0F172A" }}>
                {t("confirm.leaveSection")}
              </h2>
            </div>
            <p style={{ margin: "0 0 20px", fontSize: "14px", color: "#64748B", lineHeight: 1.5 }}>
              {t("confirm.leaveSectionMessage")}
            </p>
            <div style={{ display: "flex", gap: "10px", justifyContent: "flex-end" }}>
              <button
                onClick={() => setShowBackConfirm(false)}
                style={{ padding: "8px 16px", borderRadius: "8px", border: "1px solid #E2E8F0", backgroundColor: "transparent", color: "#64748B", fontSize: "14px", fontWeight: 600, cursor: "pointer" }}
              >
                {t("confirm.cancel")}
              </button>
              <button
                onClick={() => { dispatch({ type: "RETURN_TO_PICKER" }); setShowBackConfirm(false); }}
                style={{ padding: "8px 16px", borderRadius: "8px", border: "none", backgroundColor: "#EF4444", color: "#FFFFFF", fontSize: "14px", fontWeight: 700, cursor: "pointer" }}
              >
                {t("confirm.confirm")}
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
