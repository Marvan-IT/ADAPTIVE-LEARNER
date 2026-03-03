import { useState, useMemo, useEffect, useCallback, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { useSession } from "../../context/SessionContext";
import AssistantPanel from "./AssistantPanel";
import AdaptiveSignalTracker from "./AdaptiveSignalTracker";
import ConceptImage from "./ConceptImage";
import { useTranslation } from "react-i18next";
import { trackEvent } from "../../utils/analytics";
import { CardSkeleton } from "../ui/Skeleton";
import {
  ChevronLeft,
  ChevronRight,
  CheckCircle,
  XCircle,
  BookOpen,
  Flag,
  Loader,
} from "lucide-react";
import { useAdaptiveStore } from "../../store/adaptiveStore";
import { updateStudentProgress } from "../../api/students";
import { useStudent } from "../../context/StudentContext";
import XPBurst from "../game/XPBurst";
import StreakMeter from "../game/StreakMeter";
import AdaptiveModeIndicator from "../game/AdaptiveModeIndicator";

const WRONG_FEEDBACK_MS = 1800;
const MAX_ADAPTIVE_CARDS = 8;

/* ─── Difficulty Badge ─── */
function DifficultyBadge({ difficulty }) {
  return (
    <div className="flex gap-0.5 items-center" title={`Difficulty: ${difficulty}/5`}>
      {[1, 2, 3, 4, 5].map((i) => (
        <span
          key={i}
          className={`text-xs ${i <= (difficulty || 3) ? "text-yellow-400" : "text-[var(--color-border)]"}`}
        >
          ★
        </span>
      ))}
    </div>
  );
}

export default function CardLearningView() {
  const { t } = useTranslation();
  const {
    cards,
    currentCardIndex,
    conceptTitle,
    session,
    goToNextCard,
    goToPrevCard,
    finishCards,
    sendAssistMessage,
    loading,
    assistLoading,
    idleTriggerCount,
    adaptiveCardLoading,
    motivationalNote,
    performanceVsBaseline,
    learningProfileSummary,
    adaptationApplied,
    difficultyBias,
    setDifficultyBias,
  } = useSession();

  const { student } = useStudent();

  const mode = useAdaptiveStore((s) => s.mode);
  const awardXP = useAdaptiveStore((s) => s.awardXP);
  const recordAnswer = useAdaptiveStore((s) => s.recordAnswer);
  const updateMode = useAdaptiveStore((s) => s.updateMode);

  const card = cards[currentCardIndex];
  const MIN_CARDS_BEFORE_FINISH = 4;
  const isLastCard = (currentCardIndex === cards.length - 1 || cards.length >= MAX_ADAPTIVE_CARDS)
    && currentCardIndex >= MIN_CARDS_BEFORE_FINISH - 1;

  // Per-card question state: { mcqIdx, tfIdx, mcqCorrect, tfCorrect, mcqFeedback, tfFeedback }
  const [cardStates, setCardStates] = useState({});
  const feedbackTimerRef = useRef(null);

  // Assistant panel reveal: hidden until first answer submitted
  const [showAssistant, setShowAssistant] = useState(false);

  // Per-card signal tracking state (for AdaptiveSignalTracker display)
  const [wrongAttemptsDisplay, setWrongAttemptsDisplay] = useState(0);
  const [hintsUsedDisplay, setHintsUsedDisplay] = useState(0);

  // Signal tracking refs — reset on each new card
  const cardStartTimeRef = useRef(null);
  const wrongAttemptsRef = useRef(0);
  const selectedWrongOptionRef = useRef(null);
  const hintsUsedRef = useRef(0);
  const prevAssistLoadingRef = useRef(false);

  // Reset signal tracking when card changes
  useEffect(() => {
    cardStartTimeRef.current = performance.now();
    wrongAttemptsRef.current = 0;
    selectedWrongOptionRef.current = null;
    hintsUsedRef.current = 0;
    setWrongAttemptsDisplay(0);
    setHintsUsedDisplay(0);
  }, [currentCardIndex]);

  // Track hints via assistLoading transitions (false → true = one hint request)
  useEffect(() => {
    if (assistLoading && !prevAssistLoadingRef.current) {
      hintsUsedRef.current += 1;
      setHintsUsedDisplay(hintsUsedRef.current);
    }
    prevAssistLoadingRef.current = !!assistLoading;
  }, [assistLoading]);

  // Sync adaptive mode when learningProfileSummary updates
  useEffect(() => {
    if (learningProfileSummary) {
      updateMode(learningProfileSummary);
    }
  }, [learningProfileSummary]);

  const getCardState = useCallback(
    (idx) =>
      cardStates[idx] || {
        mcqIdx: 0,
        tfIdx: 0,
        mcqCorrect: false,
        tfCorrect: false,
        mcqFeedback: null, // { correct, explanation, answer }
        tfFeedback: null,
      },
    [cardStates]
  );

  const cs = getCardState(currentCardIndex);

  // Split questions into pools
  const mcqPool = useMemo(
    () => (card ? card.questions.filter((q) => q.type === "mcq") : []),
    [card]
  );
  const tfPool = useMemo(
    () => (card ? card.questions.filter((q) => q.type === "true_false") : []),
    [card]
  );

  const currentMcq = mcqPool[cs.mcqIdx % Math.max(mcqPool.length, 1)] || null;
  const currentTf = tfPool[cs.tfIdx % Math.max(tfPool.length, 1)] || null;
  const canProceed = cs.mcqCorrect && cs.tfCorrect;

  // Track card viewed on card change
  useEffect(() => {
    if (card) {
      trackEvent("card_viewed", {
        card_index: currentCardIndex,
        card_title: card.title,
        concept_id: session?.concept_id,
        concept_title: conceptTitle,
      });
    }
  }, [currentCardIndex, card]);

  // Cleanup timer on unmount
  useEffect(() => {
    return () => {
      if (feedbackTimerRef.current) clearTimeout(feedbackTimerRef.current);
    };
  }, []);

  const updateCardState = useCallback(
    (idx, updates) => {
      setCardStates((prev) => ({
        ...prev,
        [idx]: { ...getCardState(idx), ...updates },
      }));
    },
    [getCardState]
  );

  // Handle MCQ answer
  const handleMcqAnswer = useCallback(
    (optionIndex) => {
      if (cs.mcqCorrect || cs.mcqFeedback) return;
      const q = currentMcq;
      if (!q) return;
      const correct = optionIndex === q.correct_index;
      trackEvent("question_answered", { question_type: "mcq", correct, card_index: currentCardIndex, concept_id: session?.concept_id, concept_title: conceptTitle });

      // XP + streak tracking
      if (correct) {
        awardXP(10);
        recordAnswer(true);
        // Fire-and-forget DB sync — non-critical, silently ignore failures
        const { streak } = useAdaptiveStore.getState();
        updateStudentProgress(student?.id, 10, streak).catch(() => {});
      } else {
        recordAnswer(false);
      }

      // Reveal assistant panel on first answer
      setShowAssistant(true);

      updateCardState(currentCardIndex, {
        mcqFeedback: { correct, explanation: q.explanation, answer: optionIndex },
        ...(correct ? { mcqCorrect: true } : {}),
      });

      if (!correct) {
        // Track wrong attempt signals
        wrongAttemptsRef.current += 1;
        selectedWrongOptionRef.current = optionIndex;
        setWrongAttemptsDisplay(wrongAttemptsRef.current);

        // Auto-hint via assistant
        sendAssistMessage(
          `The student got this question wrong: "${q.question}". Give a helpful hint about this topic without revealing the answer.`,
          "user"
        );
        // Swap to backup after delay
        feedbackTimerRef.current = setTimeout(() => {
          setCardStates((prev) => {
            const prevState = prev[currentCardIndex] || getCardState(currentCardIndex);
            return {
              ...prev,
              [currentCardIndex]: {
                ...prevState,
                mcqIdx: prevState.mcqIdx + 1,
                mcqFeedback: null,
              },
            };
          });
        }, WRONG_FEEDBACK_MS);
      }
    },
    [cs, currentMcq, currentCardIndex, updateCardState, sendAssistMessage, getCardState]
  );

  // Handle T/F answer
  const handleTfAnswer = useCallback(
    (value) => {
      if (cs.tfCorrect || cs.tfFeedback) return;
      const q = currentTf;
      if (!q) return;
      const correct = value === q.correct_answer;
      trackEvent("question_answered", { question_type: "true_false", correct, card_index: currentCardIndex, concept_id: session?.concept_id, concept_title: conceptTitle });

      // XP + streak tracking
      if (correct) {
        awardXP(10);
        recordAnswer(true);
        // Fire-and-forget DB sync — non-critical, silently ignore failures
        const { streak } = useAdaptiveStore.getState();
        updateStudentProgress(student?.id, 10, streak).catch(() => {});
      } else {
        recordAnswer(false);
      }

      // Reveal assistant panel on first answer
      setShowAssistant(true);

      updateCardState(currentCardIndex, {
        tfFeedback: { correct, explanation: q.explanation, answer: value },
        ...(correct ? { tfCorrect: true } : {}),
      });

      if (!correct) {
        // Track wrong attempt signals
        wrongAttemptsRef.current += 1;
        setWrongAttemptsDisplay(wrongAttemptsRef.current);

        sendAssistMessage(
          `The student got this question wrong: "${q.question}". Give a helpful hint about this topic without revealing the answer.`,
          "user"
        );
        feedbackTimerRef.current = setTimeout(() => {
          setCardStates((prev) => {
            const prevState = prev[currentCardIndex] || getCardState(currentCardIndex);
            return {
              ...prev,
              [currentCardIndex]: {
                ...prevState,
                tfIdx: prevState.tfIdx + 1,
                tfFeedback: null,
              },
            };
          });
        }, WRONG_FEEDBACK_MS);
      }
    },
    [cs, currentTf, currentCardIndex, updateCardState, sendAssistMessage, getCardState]
  );

  // Collect signals and call adaptive goToNextCard
  const handleNextCard = useCallback(async () => {
    await goToNextCard({
      cardIndex:           currentCardIndex,
      timeOnCardSec:       cardStartTimeRef.current !== null ? (performance.now() - cardStartTimeRef.current) / 1000 : 0,
      wrongAttempts:       wrongAttemptsRef.current,
      selectedWrongOption: selectedWrongOptionRef.current,
      hintsUsed:           hintsUsedRef.current,
      idleTriggers:        idleTriggerCount,
      difficultyBias:      difficultyBias ?? null,
    });
    setDifficultyBias(null);
    setShowAssistant(false);
  }, [currentCardIndex, idleTriggerCount, goToNextCard, difficultyBias, setDifficultyBias]);

  // Loading skeleton while adaptive card is being fetched
  if (adaptiveCardLoading) {
    return (
      <div className="flex gap-4 items-start">
        <div className="flex-1 min-w-0">
          <CardSkeleton />
          <p style={{
            textAlign: "center",
            color: "var(--color-text-muted)",
            fontSize: "0.9rem",
            marginTop: "0.75rem",
            fontWeight: 600,
          }}>
            {t("learning.generatingCard")}
          </p>
        </div>
        <div style={{ width: "320px", flexShrink: 0 }}>
          <AssistantPanel />
        </div>
      </div>
    );
  }

  if (!card) return null;

  return (
    <div className="flex gap-6 items-start">
      {/* ─── Main Card Area ─── */}
      <div className="flex-1 min-w-0 transition-all duration-500">
        {/* Segmented progress bar */}
        <div className="flex gap-1 w-full mb-4">
          {cards.map((_, i) => {
            const csDot = cardStates[i];
            const isDone = csDot?.mcqCorrect && csDot?.tfCorrect;
            return (
              <div
                key={i}
                className={`h-1.5 flex-1 rounded-full transition-all duration-300 ${
                  isDone
                    ? "bg-[var(--color-success)]"
                    : i === currentCardIndex
                    ? "bg-[var(--color-primary)]"
                    : i < currentCardIndex
                    ? "bg-[var(--color-primary)]/60"
                    : "bg-[var(--color-border)]"
                }`}
              />
            );
          })}
        </div>

        {/* Motivational micro-feedback banner */}
        {motivationalNote && (
          <div style={{
            marginBottom: "0.75rem",
            padding: "0.5rem 1rem",
            borderRadius: "var(--radius-md)",
            backgroundColor: "color-mix(in srgb, var(--color-success) 10%, var(--color-surface))",
            border: "1.5px solid color-mix(in srgb, var(--color-success) 30%, var(--color-border))",
            color: "var(--color-text)",
            fontSize: "0.875rem",
            fontWeight: 600,
            display: "flex",
            alignItems: "center",
            gap: "0.5rem",
          }}>
            {performanceVsBaseline === "FASTER" && <span>⚡</span>}
            {motivationalNote}
          </div>
        )}

        {/* Card Content */}
        <div
          className={`${mode === "SLOW" ? "adaptive-slow" : ""} ${mode === "EXCELLING" ? "adaptive-excelling" : ""} ${mode === "STRUGGLING" ? "adaptive-struggling" : ""}`}
          style={{
            backgroundColor: "var(--color-surface)",
            borderRadius: "16px",
            border: "2px solid var(--color-border)",
            overflow: "hidden",
          }}
        >
          {/* Card Header */}
          <div
            style={{
              background: "linear-gradient(135deg, var(--color-primary), var(--color-accent))",
              padding: "1rem 1.5rem",
              display: "flex",
              alignItems: "center",
              gap: "0.75rem",
            }}
          >
            <div
              style={{
                width: "36px",
                height: "36px",
                borderRadius: "50%",
                backgroundColor: "rgba(255,255,255,0.2)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: "#fff",
                fontWeight: 800,
                fontSize: "0.9rem",
              }}
            >
              {currentCardIndex + 1}
            </div>
            <div className="flex-1 min-w-0">
              <div style={{ color: "#fff", fontWeight: 700, fontSize: "1.05rem" }}>
                {card.title}
              </div>
              <div style={{ color: "rgba(255,255,255,0.8)", fontSize: "0.78rem", fontWeight: 500 }}>
                {conceptTitle} — {t("learning.cardProgress", { current: currentCardIndex + 1, total: cards.length })}
              </div>
            </div>
            {/* Game HUD in header */}
            <div style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
              <StreakMeter compact />
              <AdaptiveModeIndicator compact />
              {card.difficulty != null && (
                <DifficultyBadge difficulty={card.difficulty} />
              )}
            </div>
          </div>

          {/* Card Body */}
          <div style={{ padding: "1.5rem 1.75rem" }}>
            <div className="markdown-content">
              <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>
                {card.content}
              </ReactMarkdown>
            </div>

            {/* Card Images */}
            {card.images?.filter((img) => img.url).length > 0 && (
              <div style={{ marginTop: "1rem" }}>
                {card.images
                  .filter((img) => img.url)
                  .map((img, i) => (
                    <ConceptImage key={i} img={img} maxWidth="500px" />
                  ))}
              </div>
            )}

            {/* Questions Section */}
            <div
              style={{
                marginTop: "1.5rem",
                paddingTop: "1.25rem",
                borderTop: "2px solid var(--color-border)",
              }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "0.4rem",
                  fontSize: "0.9rem",
                  fontWeight: 700,
                  color: "var(--color-primary)",
                  marginBottom: "1rem",
                }}
              >
                <BookOpen size={16} />
                {t("learning.testUnderstanding")}
              </div>

              {/* MCQ Question */}
              {currentMcq && (
                <MCQBlock
                  question={currentMcq}
                  index={1}
                  feedback={cs.mcqFeedback}
                  isCorrect={cs.mcqCorrect}
                  onAnswer={handleMcqAnswer}
                />
              )}

              {/* True/False Question */}
              {currentTf && (
                <TFBlock
                  question={currentTf}
                  index={2}
                  feedback={cs.tfFeedback}
                  isCorrect={cs.tfCorrect}
                  onAnswer={handleTfAnswer}
                />
              )}
            </div>
          </div>
        </div>

        {/* Adaptive Signal Tracker */}
        <AdaptiveSignalTracker
          wrongAttempts={wrongAttemptsDisplay}
          hintsUsed={hintsUsedDisplay}
          idleTriggers={idleTriggerCount}
          learningProfileSummary={learningProfileSummary}
          adaptationApplied={adaptationApplied}
          cardIndex={currentCardIndex}
        />

        {/* Mastery readiness bar */}
        {currentCardIndex >= 2 && learningProfileSummary?.confidence_score != null && (
          <div className="mt-2">
            <div className="flex justify-between text-xs mb-1" style={{ color: "var(--color-text-muted)" }}>
              <span>Mastery readiness</span>
              <span>{Math.round(learningProfileSummary.confidence_score * 100)}%</span>
            </div>
            <div
              className="h-1.5 rounded-full overflow-hidden"
              style={{ backgroundColor: "var(--color-border)" }}
            >
              <div
                className="h-full rounded-full transition-all duration-500"
                style={{
                  width: `${learningProfileSummary.confidence_score * 100}%`,
                  backgroundColor: "var(--color-primary)",
                }}
              />
            </div>
          </div>
        )}

        {/* Too Easy / Too Hard difficulty bias buttons */}
        {currentCardIndex > 0 && (
          <div className="flex gap-2 mt-3">
            <button
              onClick={() => setDifficultyBias(difficultyBias === "TOO_EASY" ? null : "TOO_EASY")}
              style={{
                padding: "0.375rem 0.75rem",
                fontSize: "0.75rem",
                borderRadius: "var(--radius-full)",
                border: `1.5px solid ${difficultyBias === "TOO_EASY" ? "var(--color-primary)" : "var(--color-border)"}`,
                backgroundColor: difficultyBias === "TOO_EASY" ? "var(--color-primary)" : "transparent",
                color: difficultyBias === "TOO_EASY" ? "#fff" : "var(--color-text-muted)",
                cursor: "pointer",
                fontFamily: "inherit",
                fontWeight: 600,
                transition: "all var(--motion-fast)",
              }}
            >
              Too Easy
            </button>
            <button
              onClick={() => setDifficultyBias(difficultyBias === "TOO_HARD" ? null : "TOO_HARD")}
              style={{
                padding: "0.375rem 0.75rem",
                fontSize: "0.75rem",
                borderRadius: "var(--radius-full)",
                border: `1.5px solid ${difficultyBias === "TOO_HARD" ? "#ef4444" : "var(--color-border)"}`,
                backgroundColor: difficultyBias === "TOO_HARD" ? "#ef4444" : "transparent",
                color: difficultyBias === "TOO_HARD" ? "#fff" : "var(--color-text-muted)",
                cursor: "pointer",
                fontFamily: "inherit",
                fontWeight: 600,
                transition: "all var(--motion-fast)",
              }}
            >
              Too Hard
            </button>
          </div>
        )}

        {/* Navigation Buttons */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginTop: "1rem",
            gap: "0.5rem",
          }}
        >
          <button
            onClick={goToPrevCard}
            disabled={currentCardIndex === 0}
            style={{
              display: "flex",
              alignItems: "center",
              gap: "0.4rem",
              padding: "0.7rem 1.2rem",
              borderRadius: "12px",
              border: "2px solid var(--color-border)",
              backgroundColor: "var(--color-surface)",
              color: currentCardIndex === 0 ? "var(--color-text-muted)" : "var(--color-text)",
              fontWeight: 600,
              fontSize: "0.9rem",
              cursor: currentCardIndex === 0 ? "not-allowed" : "pointer",
              fontFamily: "inherit",
              opacity: currentCardIndex === 0 ? 0.5 : 1,
            }}
          >
            <ChevronLeft size={18} /> {t("learning.previous")}
          </button>

          {isLastCard && canProceed ? (
            <button
              onClick={() => finishCards({
                cardIndex:         currentCardIndex,
                timeOnCardSec:     cardStartTimeRef.current !== null ? (performance.now() - cardStartTimeRef.current) / 1000 : 0,
                wrongAttempts:     wrongAttemptsRef.current,
                hintsUsed:         hintsUsedRef.current,
                idleTriggers:      idleTriggerCount,
                adaptationApplied: adaptationApplied ?? null,
              })}
              disabled={loading}
              style={{
                display: "flex",
                alignItems: "center",
                gap: "0.4rem",
                padding: "0.7rem 1.5rem",
                borderRadius: "12px",
                border: "none",
                backgroundColor: loading ? "var(--color-border)" : "var(--color-success)",
                color: "#fff",
                fontWeight: 700,
                fontSize: "0.95rem",
                cursor: loading ? "not-allowed" : "pointer",
                fontFamily: "inherit",
                boxShadow: loading ? "none" : "0 4px 12px rgba(34,197,94,0.3)",
              }}
            >
              {loading ? (
                <>
                  <Loader size={18} style={{ animation: "spin 1s linear infinite" }} />
                  {t("learning.startingChat")}
                </>
              ) : (
                <>
                  <Flag size={18} /> {t("learning.finishCards")}
                </>
              )}
            </button>
          ) : (
            <button
              onClick={handleNextCard}
              disabled={!canProceed || isLastCard}
              style={{
                display: "flex",
                alignItems: "center",
                gap: "0.4rem",
                padding: "0.7rem 1.2rem",
                borderRadius: "12px",
                border: "none",
                backgroundColor: canProceed && !isLastCard ? "var(--color-primary)" : "var(--color-border)",
                color: canProceed && !isLastCard ? "#fff" : "var(--color-text-muted)",
                fontWeight: 600,
                fontSize: "0.9rem",
                cursor: canProceed && !isLastCard ? "pointer" : "not-allowed",
                fontFamily: "inherit",
              }}
            >
              {t("learning.next")} <ChevronRight size={18} />
            </button>
          )}
        </div>
      </div>

      {/* ─── Assistant Panel — slides in after first answer ─── */}
      <div
        className="transition-all duration-500 overflow-hidden"
        style={{
          width: showAssistant ? "320px" : "0px",
          opacity: showAssistant ? 1 : 0,
          flexShrink: 0,
          position: "sticky",
          top: "70px",
          alignSelf: "flex-start",
        }}
      >
        <div style={{ width: "320px" }}>
          <AssistantPanel />
        </div>
      </div>

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      <XPBurst />
    </div>
  );
}

/* ─── MCQ Question Block (pill-shaped buttons) ─── */
function MCQBlock({ question, index, feedback, isCorrect, onAnswer }) {
  const { t } = useTranslation();
  const answered = feedback !== null;
  const isLocked = isCorrect || answered;

  return (
    <div
      style={{
        marginBottom: "1.25rem",
        padding: "1rem",
        borderRadius: "12px",
        border: `2px solid ${
          isCorrect
            ? "var(--color-success)"
            : answered && !feedback?.correct
            ? "var(--color-danger)"
            : "var(--color-border)"
        }`,
        backgroundColor: isCorrect
          ? "rgba(34,197,94,0.05)"
          : answered && !feedback?.correct
          ? "rgba(239,68,68,0.05)"
          : "var(--color-bg)",
        animation: answered && !feedback?.correct ? "shake 0.35s ease-out" : "none",
      }}
    >
      <div
        style={{
          fontSize: "0.95rem",
          fontWeight: 600,
          color: "var(--color-text)",
          marginBottom: "0.75rem",
          lineHeight: 1.5,
        }}
      >
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            width: "24px",
            height: "24px",
            borderRadius: "50%",
            backgroundColor: "var(--color-primary)",
            color: "#fff",
            fontSize: "0.75rem",
            fontWeight: 800,
            marginRight: "0.5rem",
            flexShrink: 0,
          }}
        >
          {index}
        </span>
        <ReactMarkdown
          remarkPlugins={[remarkMath]}
          rehypePlugins={[rehypeKatex]}
          components={{ p: ({ children }) => <span>{children}</span> }}
        >
          {question.question}
        </ReactMarkdown>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: "0.4rem" }}>
        {question.options.map((opt, oi) => {
          const isSelected = answered && feedback?.answer === oi;
          const optIsCorrect = oi === question.correct_index;
          const showCorrect = answered && optIsCorrect;
          const showWrong = isSelected && !feedback?.correct;

          let borderColor = "var(--color-border)";
          let bgColor = "var(--color-surface)";
          let textColor = "var(--color-text)";

          if (showCorrect) {
            borderColor = "#22c55e";
            bgColor = "rgba(34,197,94,0.1)";
            textColor = "#166534";
          } else if (showWrong) {
            borderColor = "#ef4444";
            bgColor = "rgba(239,68,68,0.1)";
            textColor = "#991b1b";
          }

          return (
            <button
              key={oi}
              onClick={() => onAnswer(oi)}
              disabled={isLocked}
              style={{
                display: "flex",
                alignItems: "center",
                gap: "0.75rem",
                width: "100%",
                padding: "0.75rem 1rem",
                borderRadius: "9999px",
                border: `2px solid ${borderColor}`,
                backgroundColor: bgColor,
                color: textColor,
                fontSize: "0.9rem",
                fontWeight: isSelected || showCorrect ? 700 : 500,
                cursor: isLocked ? "default" : "pointer",
                fontFamily: "inherit",
                textAlign: "left",
                transition: "all 0.2s",
                animation: showWrong ? "shake 0.4s ease" : "none",
              }}
              onMouseEnter={(e) => {
                if (!isLocked && !showCorrect && !showWrong) {
                  e.currentTarget.style.borderColor = "var(--color-primary)";
                  e.currentTarget.style.backgroundColor = "color-mix(in srgb, var(--color-primary) 5%, var(--color-surface))";
                }
              }}
              onMouseLeave={(e) => {
                if (!isLocked && !showCorrect && !showWrong) {
                  e.currentTarget.style.borderColor = "var(--color-border)";
                  e.currentTarget.style.backgroundColor = "var(--color-surface)";
                }
              }}
            >
              {/* Label circle A, B, C, D */}
              <span
                style={{
                  width: "28px",
                  height: "28px",
                  borderRadius: "50%",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  flexShrink: 0,
                  fontSize: "0.75rem",
                  fontWeight: 700,
                  backgroundColor: showCorrect
                    ? "#22c55e"
                    : showWrong
                    ? "#ef4444"
                    : "color-mix(in srgb, var(--color-primary) 10%, var(--color-surface))",
                  color: showCorrect || showWrong ? "#fff" : "var(--color-primary)",
                }}
              >
                {showCorrect ? <CheckCircle size={14} /> : showWrong ? <XCircle size={14} /> : String.fromCharCode(65 + oi)}
              </span>
              <ReactMarkdown
                remarkPlugins={[remarkMath]}
                rehypePlugins={[rehypeKatex]}
                components={{ p: ({ children }) => <span>{children}</span> }}
              >
                {opt}
              </ReactMarkdown>
            </button>
          );
        })}
      </div>

      {/* Feedback */}
      {answered && (
        <div
          style={{
            marginTop: "0.6rem",
            padding: "0.5rem 0.75rem",
            borderRadius: "8px",
            backgroundColor: feedback.correct ? "rgba(34,197,94,0.08)" : "rgba(239,68,68,0.08)",
            fontSize: "0.85rem",
            lineHeight: 1.4,
            color: "var(--color-text)",
          }}
        >
          <span style={{ fontWeight: 700, color: feedback.correct ? "var(--color-success)" : "var(--color-danger)" }}>
            {feedback.correct ? t("learning.correct") + " " : t("learning.incorrect") + " "}
          </span>
          {feedback.correct && feedback.explanation}
        </div>
      )}
    </div>
  );
}

/* ─── True/False Question Block ─── */
function TFBlock({ question, index, feedback, isCorrect, onAnswer }) {
  const { t } = useTranslation();
  const answered = feedback !== null;
  const isLocked = isCorrect || (answered && !feedback?.correct);

  return (
    <div
      style={{
        marginBottom: "1.25rem",
        padding: "1rem",
        borderRadius: "12px",
        border: `2px solid ${
          isCorrect
            ? "var(--color-success)"
            : answered && !feedback?.correct
            ? "var(--color-danger)"
            : "var(--color-border)"
        }`,
        backgroundColor: isCorrect
          ? "rgba(34,197,94,0.05)"
          : answered && !feedback?.correct
          ? "rgba(239,68,68,0.05)"
          : "var(--color-bg)",
      }}
    >
      <div
        style={{
          fontSize: "0.95rem",
          fontWeight: 600,
          color: "var(--color-text)",
          marginBottom: "0.75rem",
          lineHeight: 1.5,
        }}
      >
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            width: "24px",
            height: "24px",
            borderRadius: "50%",
            backgroundColor: "var(--color-primary)",
            color: "#fff",
            fontSize: "0.75rem",
            fontWeight: 800,
            marginRight: "0.5rem",
            flexShrink: 0,
          }}
        >
          {index}
        </span>
        <ReactMarkdown
          remarkPlugins={[remarkMath]}
          rehypePlugins={[rehypeKatex]}
          components={{ p: ({ children }) => <span>{children}</span> }}
        >
          {question.question}
        </ReactMarkdown>
      </div>

      <div style={{ display: "flex", gap: "0.5rem" }}>
        {["true", "false"].map((val) => {
          const isSelected = answered && feedback?.answer === val;
          const valIsCorrect = val === question.correct_answer;
          const showCorrect = answered && valIsCorrect;
          const showWrong = isSelected && !feedback?.correct;

          return (
            <button
              key={val}
              onClick={() => onAnswer(val)}
              disabled={isLocked}
              style={{
                flex: 1,
                padding: "0.65rem",
                borderRadius: "10px",
                border: `2px solid ${
                  showCorrect ? "var(--color-success)" : showWrong ? "var(--color-danger)" : "var(--color-border)"
                }`,
                backgroundColor: showCorrect
                  ? "rgba(34,197,94,0.1)"
                  : showWrong
                  ? "rgba(239,68,68,0.1)"
                  : "var(--color-surface)",
                color: "var(--color-text)",
                fontSize: "0.95rem",
                fontWeight: 700,
                cursor: isLocked ? "default" : "pointer",
                fontFamily: "inherit",
                textTransform: "capitalize",
              }}
            >
              {showCorrect && <CheckCircle size={14} style={{ marginRight: "0.3rem", verticalAlign: "middle" }} />}
              {showWrong && <XCircle size={14} style={{ marginRight: "0.3rem", verticalAlign: "middle" }} />}
              {val}
            </button>
          );
        })}
      </div>

      {/* Feedback */}
      {answered && (
        <div
          style={{
            marginTop: "0.6rem",
            padding: "0.5rem 0.75rem",
            borderRadius: "8px",
            backgroundColor: feedback.correct ? "rgba(34,197,94,0.08)" : "rgba(239,68,68,0.08)",
            fontSize: "0.85rem",
            lineHeight: 1.4,
            color: "var(--color-text)",
          }}
        >
          <span style={{ fontWeight: 700, color: feedback.correct ? "var(--color-success)" : "var(--color-danger)" }}>
            {feedback.correct ? t("learning.correct") + " " : t("learning.incorrect") + " "}
          </span>
          {feedback.correct && feedback.explanation}
        </div>
      )}
    </div>
  );
}
