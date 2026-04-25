import { useState, useMemo, useEffect, useCallback, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { useSession } from "../../context/SessionContext";
import AssistantPanel from "./AssistantPanel";
import AdaptiveSignalTracker from "./AdaptiveSignalTracker";
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
import { regenerateMCQ } from "../../api/sessions";
import { resolveImageUrl } from "../../api/client";
import { useStudent } from "../../context/StudentContext";
import XPBurst from "../game/XPBurst";
import StreakMeter from "../game/StreakMeter";
import AdaptiveModeIndicator from "../game/AdaptiveModeIndicator";

const WRONG_FEEDBACK_MS = 1800;

/* ─── Difficulty Badge ─── */
function DifficultyBadge({ difficulty }) {
  const { t } = useTranslation();
  return (
    <div
      style={{ display: "flex", gap: "2px", alignItems: "center" }}
      title={t("learning.difficultyLabel", { value: difficulty, max: 5 })}
    >
      {[1, 2, 3, 4, 5].map((i) => (
        <span
          key={i}
          style={{
            fontSize: "0.75rem",
            color: i <= (difficulty || 3) ? "#facc15" : "#E2E8F0",
          }}
        >
          ★
        </span>
      ))}
    </div>
  );
}


/* ─── CHECKIN card body ─── */
function CheckInCard({ card, onSelect }) {
  const [selected, setSelected] = useState(null);
  const options = card.options || [];

  const moodColors = ["var(--color-primary)", "#22c55e", "var(--color-warning, #FBBF24)", "#ef4444"];

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "1rem", paddingTop: "1rem", paddingBottom: "1rem" }}>
      <div className="markdown-content" style={{ textAlign: "center", maxWidth: "480px" }}>
        <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]} skipHtml={true}>
          {card.content}
        </ReactMarkdown>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem", width: "100%", maxWidth: "380px" }}>
        {options.map((opt, i) => (
          <button
            key={i}
            onClick={() => { setSelected(i); onSelect?.(i); }}
            style={{
              padding: "0.85rem 1.25rem",
              borderRadius: "12px",
              border: `2px solid ${selected === i ? moodColors[i % moodColors.length] : "var(--color-border)"}`,
              backgroundColor: selected === i
                ? `${moodColors[i % moodColors.length]}18`
                : "var(--color-surface)",
              color: selected === i ? moodColors[i % moodColors.length] : "var(--color-text)",
              fontWeight: selected === i ? 700 : 500,
              fontSize: "0.95rem",
              cursor: "pointer",
              fontFamily: "inherit",
              textAlign: "center",
              transition: "all 0.2s",
            }}
            onMouseEnter={(e) => {
              if (selected !== i) {
                e.currentTarget.style.borderColor = moodColors[i % moodColors.length];
                e.currentTarget.style.backgroundColor = `${moodColors[i % moodColors.length]}10`;
              }
            }}
            onMouseLeave={(e) => {
              if (selected !== i) {
                e.currentTarget.style.borderColor = "var(--color-border)";
                e.currentTarget.style.backgroundColor = "var(--color-surface)";
              }
            }}
          >
            {opt}
          </button>
        ))}
      </div>
    </div>
  );
}

export default function CardLearningView({ remediationMode = false, onCardStatesChange }) {
  const { t } = useTranslation();
  const {
    cards,
    currentCardIndex,
    maxReachedIndex,
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
    hasMoreConcepts,
    conceptsTotal,
    conceptsCoveredCount,
    currentChunkIndex,
    totalChunks,
    nextCardInFlight,
    // Chunk navigation
    chunkList,
    chunkIndex,
    nextChunkInFlight,
    nextChunkCards,
    goToNextChunk,
    // Chunk completion
    completeChunkAction,
    completeChunkItem,
    currentChunkMode,
    currentChunkId,
    modeJustChanged,
    chunkQuestions,
    dispatch,
  } = useSession();

  const { student } = useStudent();

  const mode = useAdaptiveStore((s) => s.mode);
  const awardXP = useAdaptiveStore((s) => s.awardXP);
  const recordAnswer = useAdaptiveStore((s) => s.recordAnswer);
  const updateMode = useAdaptiveStore((s) => s.updateMode);

  const card = cards[currentCardIndex];
  // New schema: cards are discriminated by whether they have a question, not by card_type.
  const hasQuestion = !!(card?.question || card?.quick_check || card?.questions?.length);
  const cardType = hasQuestion ? "TEACH" : "VISUAL";

  const allSectionsDone = !hasMoreConcepts;
  const isLastChunk = chunkList.length === 0 || chunkIndex >= chunkList.length - 1;
  const isLastCard = currentCardIndex === cards.length - 1 && allSectionsDone && isLastChunk;
  const isLastCardOfNonFinalChunk = currentCardIndex === cards.length - 1 && chunkList.length > 1 && !isLastChunk;

  // Chunk MCQ tracking — correct/total counts for completeChunk call
  const [chunkCorrect, setChunkCorrect] = useState(0);
  const [chunkTotal, setChunkTotal] = useState(0);

  // Per-card question state: { mcqIdx, mcqCorrect, mcqFeedback, quickCheckDone, checkinDone }
  const [cardStates, setCardStates] = useState({});
  const feedbackTimerRef = useRef(null);

  // Notify parent (LearningPage) when cardStates changes so VerticalProgressRail gets live data
  useEffect(() => {
    if (onCardStatesChange) onCardStatesChange(cardStates);
  }, [cardStates, onCardStatesChange]);

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
        mcqCorrect: false,
        mcqFeedback: null, // { correct, explanation, answer }
        quickCheckDone: false,
        checkinDone: false,
        replacementMcq: null, // populated after a wrong answer
      },
    [cardStates]
  );

  const cs = getCardState(currentCardIndex);

  // Unified question source: prefer replacementMcq (generated after wrong answer),
  // then new schema card.question.
  // Normalize to a consistent shape: { question, options, correct_index, explanation }
  const mcq = useMemo(() => {
    const raw = cs.replacementMcq || card?.question || null;
    if (!raw) return null;
    // New schema uses "text" field; old schema uses "question" field
    return raw.text ? { ...raw, question: raw.text } : raw;
  }, [cs.replacementMcq, card]);

  // Split questions into pools (only for cards that have questions[] — old schema)
  const mcqPool = useMemo(
    () => (card?.questions ? card.questions.filter((q) => q.type === "mcq") : []),
    [card]
  );

  const currentMcq = mcqPool[cs.mcqIdx % Math.max(mcqPool.length, 1)] || null;

  // Real-time mastery readiness from current session: fraction of seen MCQ cards answered correctly
  const masteryData = useMemo(() => {
    const seenCount = Math.min(currentCardIndex + 1, cards.length);
    let withMCQ = 0;
    let correct = 0;
    for (let i = 0; i < seenCount; i++) {
      const c = cards[i];
      if (!c) continue;
      if (c.question) {
        withMCQ++;
        const csi = cardStates[i] || {};
        if (csi.quickCheckDone || csi.mcqCorrect) correct++;
      }
    }
    return { withMCQ, correct, score: withMCQ > 0 ? correct / withMCQ : 0 };
  }, [cards, cardStates, currentCardIndex]);

  // canProceed: content-only cards auto-proceed; question cards require a correct answer
  const canProceed = useMemo(() => {
    if (!card) return false;
    if (!hasQuestion) return true; // content card — no question to answer, auto-proceed
    // MCQ card — requires answer
    const qcDone = !mcq || cs.quickCheckDone;
    const mcqDone = mcqPool.length === 0 || cs.mcqCorrect;
    return qcDone && mcqDone;
  }, [card, hasQuestion, mcq, mcqPool.length, cs]);

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

  // Mode change acknowledgment — clear the flag after noting the change
  useEffect(() => {
    if (modeJustChanged && dispatch) {
      dispatch({ type: "MODE_CHANGE_ACKNOWLEDGED" });
    }
  }, [modeJustChanged, dispatch]);

  const updateCardState = useCallback(
    (idx, updates) => {
      setCardStates((prev) => ({
        ...prev,
        [idx]: { ...getCardState(idx), ...updates },
      }));
    },
    [getCardState]
  );

  // Handle unified card.question MCQ answer (new schema + quick_check fallback)
  const handleUnifiedMcqAnswer = useCallback(
    (optionIndex) => {
      if (cs.quickCheckDone || cs.mcqFeedback) return;
      if (!mcq) return;
      const correct = optionIndex === mcq.correct_index;
      trackEvent("question_answered", { question_type: "mcq", correct, card_index: currentCardIndex, concept_id: session?.concept_id, concept_title: conceptTitle });

      // Track for chunk completion scoring
      setChunkTotal((n) => n + 1);
      if (correct) setChunkCorrect((n) => n + 1);

      if (correct) {
        recordAnswer(true);
      } else {
        recordAnswer(false);
      }

      setShowAssistant(true);

      updateCardState(currentCardIndex, {
        mcqFeedback: { correct, explanation: mcq.explanation, answer: optionIndex },
        ...(correct ? { quickCheckDone: true } : {}),
      });

      if (!correct) {
        wrongAttemptsRef.current += 1;
        selectedWrongOptionRef.current = optionIndex;
        setWrongAttemptsDisplay(wrongAttemptsRef.current);

        sendAssistMessage(
          `The student got this question wrong: "${mcq.question}". Give a helpful hint about this topic without revealing the answer.`,
          "user",
          { isSystemPrompt: true }
        );

        const isSecondAttempt = !!cs.replacementMcq;
        feedbackTimerRef.current = setTimeout(async () => {
          if (feedbackTimerRef.current === null) return;   // stale guard — cleared by handleNextCard
          feedbackTimerRef.current = null;
          if (isSecondAttempt) {
            const elapsedSec = cardStartTimeRef.current !== null
              ? (performance.now() - cardStartTimeRef.current) / 1000
              : 120;
            goToNextCard({
              cardIndex:           currentCardIndex,
              timeOnCardSec:       elapsedSec,
              wrongAttempts:       2,
              selectedWrongOption: selectedWrongOptionRef.current ?? null,
              hintsUsed:           hintsUsedRef.current,
              idleTriggers:        idleTriggerCount,
              reExplainCardTitle:  card?.title ?? null,
              wrongQuestion:       mcq?.question || null,
              wrongAnswerText:     mcq?.options?.[selectedWrongOptionRef.current] || null,
            });
            return;
          }
          // 1st wrong — regenerate MCQ only
          try {
            const { data } = await regenerateMCQ(session.id, {
              card_content: card.content,
              card_title: card.title,
              concept_id: session.concept_id,
              previous_question: mcq.question || mcq.text,
              language: student?.preferred_language || "en",
            });
            setCardStates((prev) => {
              const prevState = prev[currentCardIndex] || getCardState(currentCardIndex);
              return {
                ...prev,
                [currentCardIndex]: {
                  ...prevState,
                  mcqFeedback: null,
                  replacementMcq: data.question,
                },
              };
            });
          } catch {
            setCardStates((prev) => {
              const prevState = prev[currentCardIndex] || getCardState(currentCardIndex);
              return {
                ...prev,
                [currentCardIndex]: { ...prevState, mcqFeedback: null },
              };
            });
          }
        }, WRONG_FEEDBACK_MS);
      }
    },
    [cs, mcq, currentCardIndex, updateCardState, sendAssistMessage, getCardState, awardXP, recordAnswer, student, session, card]
  );

  // Handle MCQ answer (old schema — questions[] pool)
  const handleMcqAnswer = useCallback(
    (optionIndex) => {
      if (cs.mcqCorrect || cs.mcqFeedback) return;
      const q = currentMcq;
      if (!q) return;
      const correct = optionIndex === q.correct_index;
      trackEvent("question_answered", { question_type: "mcq", correct, card_index: currentCardIndex, concept_id: session?.concept_id, concept_title: conceptTitle });

      // Answer streak tracking (XP comes from backend via recordCardInteraction response)
      if (correct) {
        recordAnswer(true);
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
        wrongAttemptsRef.current += 1;
        selectedWrongOptionRef.current = optionIndex;
        setWrongAttemptsDisplay(wrongAttemptsRef.current);

        sendAssistMessage(
          `The student got this question wrong: "${q.question}". Give a helpful hint about this topic without revealing the answer.`,
          "user",
          { isSystemPrompt: true }
        );
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


  const [isSubmitting, setIsSubmitting] = useState(false);

  // Collect signals and call adaptive goToNextCard
  const handleNextCard = useCallback(async () => {
    if (isSubmitting) return;
    if (feedbackTimerRef.current) {
      clearTimeout(feedbackTimerRef.current);
      feedbackTimerRef.current = null;
    }

    setIsSubmitting(true);
    try {
      await goToNextCard({
        cardIndex:           currentCardIndex,
        timeOnCardSec:       cardStartTimeRef.current !== null ? (performance.now() - cardStartTimeRef.current) / 1000 : 0,
        wrongAttempts:       wrongAttemptsRef.current,
        selectedWrongOption: selectedWrongOptionRef.current,
        hintsUsed:           hintsUsedRef.current,
        idleTriggers:        idleTriggerCount,
        isCorrect:           cs.mcqCorrect || cs.quickCheckDone,
        difficulty:          card?.difficulty ?? null,
      });
      setShowAssistant(false);
    } finally {
      setIsSubmitting(false);
    }
  }, [currentCardIndex, idleTriggerCount, goToNextCard, isSubmitting, cs.mcqCorrect, cs.quickCheckDone, card?.difficulty]);

  const handleNextChunk = useCallback(async () => {
    // If exam questions were generated for this teaching chunk, show Q&A first
    if (chunkQuestions?.length > 0) {
      dispatch({ type: "SHOW_CHUNK_QUESTIONS" });
      return;
    }
    // No questions (exercise/info chunk) — complete and advance directly
    const chunkId = cards[currentCardIndex]?.chunk_id;
    if (chunkId && completeChunkAction) {
      await completeChunkAction(chunkId, chunkCorrect, chunkTotal, currentChunkMode || "NORMAL");
      setChunkCorrect(0);
      setChunkTotal(0);
    }
    goToNextChunk();
  }, [cards, currentCardIndex, chunkCorrect, chunkTotal, currentChunkMode,
      completeChunkAction, goToNextChunk, chunkQuestions, dispatch]);

  // Handle finish button — in remediation mode, go to recheck instead of finishCards
  const handleFinish = useCallback(() => {
    if (!allSectionsDone) return; // defensive: button should already be hidden
    const signals = {
      cardIndex:         currentCardIndex,
      timeOnCardSec:     cardStartTimeRef.current !== null ? (performance.now() - cardStartTimeRef.current) / 1000 : 0,
      wrongAttempts:     wrongAttemptsRef.current,
      hintsUsed:         hintsUsedRef.current,
      idleTriggers:      idleTriggerCount,
      adaptationApplied: adaptationApplied ?? null,
      isCorrect:         cs.mcqCorrect || cs.quickCheckDone,
      difficulty:        card?.difficulty ?? null,
    };
    finishCards(signals);
  }, [currentCardIndex, idleTriggerCount, adaptationApplied, finishCards, cs.mcqCorrect, cs.quickCheckDone, card?.difficulty]);

  // Loading skeleton while adaptive card is being fetched
  if (adaptiveCardLoading) {
    return (
      <div style={{ display: "flex", gap: "2rem", alignItems: "flex-start" }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <CardSkeleton />
          <p style={{ textAlign: "center", color: "var(--color-text-muted)", fontSize: "0.9rem", marginTop: "0.75rem", fontWeight: 600 }}>
            {t("learning.generatingCard")}
          </p>
        </div>
        <div style={{ width: "320px", flexShrink: 0 }}>
          <AssistantPanel />
        </div>
      </div>
    );
  }

  if (!card) {
    if (cards.length === 0) {
      return (
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "50vh", gap: "1rem" }}>
          <p style={{ color: "var(--color-text-muted)", fontSize: "1rem" }}>
            {(loading || nextCardInFlight) ? t("learning.generatingCards") : t("learning.noCardsError")}
          </p>
        </div>
      );
    }
    // Index temporarily out of bounds — SessionContext will self-correct
    return null;
  }

  // Build header gradient — always use the primary/accent gradient in the new schema
  const headerGradient = "linear-gradient(135deg, var(--color-primary), var(--color-accent))";

  return (
    <div style={{ display: "flex", gap: "20px", alignItems: "flex-start" }}>
      {/* ─── Main Card Area ─── */}
      <div style={{ flex: 1, minWidth: 0, transition: "all 0.5s" }}>
        {/* Segmented progress bar */}
        <ProgressDots cards={cards} cardStates={cardStates} currentCardIndex={currentCardIndex} />

        {/* Chunk (section) progress indicator — new chunk flow */}
        {chunkList.length > 1 && (
          <div style={{ textAlign: "center", fontSize: "0.75rem", color: "var(--color-text-muted, #6b7280)", marginBottom: "0.5rem" }}>
            {t("chunk.progress", { current: chunkIndex + 1, total: chunkList.length })}
          </div>
        )}

        {/* Legacy chunk progress bar — old totalChunks field */}
        {totalChunks > 0 && chunkList.length === 0 && (
          <div style={{ marginBottom: "0.75rem" }}>
            <div style={{ fontSize: "0.75rem", color: "#9ca3af", marginBottom: "0.25rem" }}>
              {t("chunk.progress", { current: currentChunkIndex + 1, total: totalChunks })}
            </div>
            <div style={{ height: "4px", backgroundColor: "#e5e7eb", borderRadius: "2px" }}>
              <div
                style={{
                  height: "100%",
                  backgroundColor: "var(--color-primary)",
                  borderRadius: "2px",
                  transition: "width 300ms ease-in-out",
                  width: `${((currentChunkIndex + 1) / totalChunks) * 100}%`,
                }}
              />
            </div>
          </div>
        )}

        {/* Practice mode banner — shown when current chunk is an exercise chunk */}
        {chunkList[chunkIndex]?.chunk_type === "exercise" && !remediationMode && (
          <div style={{
            marginBottom: "0.75rem",
            padding: "0.5rem 1rem",
            borderRadius: "12px",
            backgroundColor: "#fffbeb",
            border: "1.5px solid #fcd34d",
            color: "#92400e",
            fontSize: "0.875rem",
            fontWeight: 600,
            display: "flex",
            alignItems: "center",
            gap: "0.5rem",
          }}>
            <span aria-hidden="true">✏️</span> {t("learning.practiceMode", "Practice Mode — applying what you learned")}
          </div>
        )}

        {/* Remediation mode banner */}
        {remediationMode && <RemediationBanner />}

        {/* Motivational micro-feedback banner */}
        {motivationalNote && (
          <div
            style={{
              marginBottom: "0.75rem",
              padding: "0.5rem 1rem",
              borderRadius: "12px",
              color: "var(--color-text)",
              fontSize: "0.875rem",
              fontWeight: 600,
              display: "flex",
              alignItems: "center",
              gap: "0.5rem",
              backgroundColor: "color-mix(in srgb, var(--color-success) 10%, var(--color-surface))",
              border: "1.5px solid color-mix(in srgb, var(--color-success) 30%, var(--color-border))",
            }}
          >
            {performanceVsBaseline === "FASTER" && <span aria-hidden="true">⚡</span>}
            {motivationalNote}
          </div>
        )}

        {/* Card Content */}
        <div
          style={{ backgroundColor: "#FFFFFF", borderRadius: "16px", border: "2px solid #E2E8F0", overflow: "hidden" }}
          className={`${mode === "SLOW" ? "adaptive-slow" : ""} ${mode === "FAST" ? "adaptive-excelling" : ""} ${mode === "STRUGGLING" ? "adaptive-struggling" : ""}`}
        >
          {/* Card Header */}
          <div
            style={{ display: "flex", alignItems: "center", gap: "12px", padding: "16px 24px", background: headerGradient }}
          >
            <div style={{ width: "36px", height: "36px", borderRadius: "50%", backgroundColor: "rgba(255,255,255,0.2)", display: "flex", alignItems: "center", justifyContent: "center", color: "#FFFFFF", fontWeight: 800, fontSize: "14px", flexShrink: 0 }}>
              {currentCardIndex + 1}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ color: "#FFFFFF", fontWeight: 700, fontSize: "16px" }}>
                {card.title}
              </div>
              <div style={{ color: "rgba(255,255,255,0.8)", fontSize: "12px", fontWeight: 500 }}>
                {conceptTitle} — {t("learning.cardProgress", { current: currentCardIndex + 1, total: cards.length })}
              </div>
            </div>
            {/* Game HUD */}
            <div style={{ display: "flex", alignItems: "center", gap: "6px", flexShrink: 0 }}>
              <StreakMeter compact />
              <AdaptiveModeIndicator compact />
              {card.difficulty != null && (
                <DifficultyBadge difficulty={card.difficulty} />
              )}
            </div>
          </div>

          {/* Card Body */}
          <div style={{ padding: "24px 28px" }}>
            {/* Recovery card indicator */}
            {card?.is_recovery && (
              <div style={{ fontSize: "0.8rem", color: "var(--color-primary)", marginBottom: "0.5rem", fontWeight: 600 }}>
                &#8635; Let's approach this differently
              </div>
            )}

            {/* Direct image_url rendering — new schema */}
            {card?.image_url && (
              <div style={{ margin: "1rem 0", textAlign: "center" }}>
                <img
                  src={resolveImageUrl(card.image_url)}
                  alt={card.caption || "Diagram"}
                  style={{ maxWidth: "100%", maxHeight: "400px", borderRadius: "8px", objectFit: "contain" }}
                />
                {card.caption && (
                  <p style={{ fontSize: "0.85rem", color: "#6b7280", marginTop: "6px", fontStyle: "italic" }}>
                    {card.caption}
                  </p>
                )}
              </div>
            )}

            <>
                {/* Card content — markdown with math support */}
                <div className="markdown-content">
                  <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]} skipHtml={true}>
                    {card.content}
                  </ReactMarkdown>
                </div>

                {/* Unified MCQ block — new schema: card.question; old schema: card.quick_check fallback */}
                {mcq && mcqPool.length === 0 && cardType !== "FUN" && cardType !== "VISUAL" && (
                  <MCQBlock
                    question={mcq}
                    index={1}
                    feedback={cs.mcqFeedback}
                    isCorrect={cs.quickCheckDone}
                    onAnswer={handleUnifiedMcqAnswer}
                  />
                )}

                {/* FUN card "Got it!" tap */}
                {cardType === "FUN" && !cs.checkinDone && (
                  <div style={{ marginTop: "1.25rem" }}>
                    <button
                      onClick={() => updateCardState(currentCardIndex, { checkinDone: true })}
                      style={{
                        padding: "0.625rem 1.5rem",
                        borderRadius: "9999px",
                        border: "none",
                        backgroundColor: "var(--color-primary)",
                        color: "#ffffff",
                        fontWeight: 700,
                        fontSize: "0.9rem",
                        cursor: "pointer",
                        fontFamily: "inherit",
                      }}
                    >
                      {t("learning.gotIt")}
                    </button>
                  </div>
                )}
                {cardType === "FUN" && cs.checkinDone && (
                  <div style={{ marginTop: "0.75rem", fontSize: "0.85rem", color: "var(--color-primary)", fontWeight: 600 }}>
                    {t("learning.noted")}
                  </div>
                )}

                {/* Questions Section — old schema: cards with questions[] array */}
                {mcqPool.length > 0 && cardType !== "FUN" && cardType !== "VISUAL" && (
                  <div style={{ marginTop: "24px", paddingTop: "20px", borderTop: "2px solid #E2E8F0" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "14px", fontWeight: 700, color: "#F97316", marginBottom: "16px" }}>
                      <BookOpen size={16} />
                      {t("learning.testUnderstanding")}
                    </div>

                    {/* MCQ Question (old schema) */}
                    {currentMcq && (
                      <MCQBlock
                        question={currentMcq}
                        index={1}
                        feedback={cs.mcqFeedback}
                        isCorrect={cs.mcqCorrect}
                        onAnswer={handleMcqAnswer}
                      />
                    )}
                  </div>
                )}
              </>
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

        {/* Mastery readiness bar — computed from live in-session MCQ performance */}
        {masteryData.withMCQ > 0 && (
          <div style={{ marginTop: "0.5rem" }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.75rem", marginBottom: "0.25rem", color: "var(--color-text-muted)" }}>
              <span>{t("learning.masteryReadiness")}</span>
              <span>{masteryData.correct}/{masteryData.withMCQ} correct</span>
            </div>
            <div style={{ height: "6px", borderRadius: "9999px", overflow: "hidden", backgroundColor: "var(--color-border)" }}>
              <div
                style={{
                  height: "100%",
                  borderRadius: "9999px",
                  transition: "all 500ms",
                  width: `${masteryData.score * 100}%`,
                  backgroundColor:
                    masteryData.score >= 0.8
                      ? "var(--color-success)"
                      : masteryData.score >= 0.5
                      ? "var(--color-primary)"
                      : "var(--color-warning, #f59e0b)",
                }}
              />
            </div>
          </div>
        )}

        {/* Concept (sub-section) progress indicator */}
        {conceptsTotal > 0 && (
          <div style={{ fontSize: "0.75rem", color: "var(--color-text-muted, #888)", marginTop: "0.25rem", textAlign: "center" }}>
            {t("learning.conceptsProgress", { covered: conceptsCoveredCount, total: conceptsTotal })}
          </div>
        )}

        <NavButtons
          currentCardIndex={currentCardIndex}
          maxReachedIndex={maxReachedIndex}
          isLastCard={isLastCard}
          isLastCardOfNonFinalChunk={isLastCardOfNonFinalChunk}
          canProceed={canProceed}
          loading={loading}
          nextChunkInFlight={nextChunkInFlight}
          nextChunkCards={nextChunkCards}
          onPrev={goToPrevCard}
          onNext={handleNextCard}
          onNextChunk={handleNextChunk}
          onFinish={handleFinish}
          remediationMode={remediationMode}
          chunkQuestions={chunkQuestions}
          isSubmitting={isSubmitting}
          t={t}
        />

      </div>

      {/* ─── Assistant Panel — slides in after first answer ─── */}
      <div style={{ width: "320px", flexShrink: 0, position: "sticky", top: "70px", alignSelf: "flex-start" }}>
        <div style={{ width: "320px" }}>
          <AssistantPanel />
        </div>
      </div>

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      <XPBurst />
    </div>
  );
}


/* ─── Segmented progress bar (extracted for reuse) ─── */
function ProgressDots({ cards, cardStates, currentCardIndex }) {
  const manyCards = cards.length > 20;
  const dotSize = manyCards ? 6 : 8;
  return (
    <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: "4px", maxWidth: "100%", marginBottom: "1rem" }}>
      {cards.map((_, i) => {
        const csDot = cardStates[i];
        const isDone = csDot?.mcqCorrect || csDot?.quickCheckDone;
        const bgColor = isDone
          ? "var(--color-success)"
          : i === currentCardIndex
          ? "var(--color-primary)"
          : i < currentCardIndex
          ? "color-mix(in srgb, var(--color-primary) 60%, transparent)"
          : "var(--color-border)";
        return (
          <div
            key={i}
            style={{
              width: dotSize,
              height: dotSize,
              borderRadius: "9999px",
              transition: "all 300ms",
              flexShrink: 0,
              backgroundColor: bgColor,
            }}
          />
        );
      })}
    </div>
  );
}

/* ─── Remediation banner ─── */
function RemediationBanner() {
  return (
    <div
      style={{
        marginBottom: "0.875rem",
        padding: "0.625rem 1rem",
        borderRadius: "12px",
        color: "var(--color-text)",
        fontSize: "0.875rem",
        fontWeight: 700,
        display: "flex",
        alignItems: "center",
        gap: "0.5rem",
        backgroundColor: "color-mix(in srgb, var(--color-primary) 12%, var(--color-surface))",
        border: "1.5px solid color-mix(in srgb, var(--color-primary) 35%, var(--color-border))",
      }}
    >
      <span aria-hidden="true">💪</span>
      Let's look at these parts together!
    </div>
  );
}

/* ─── Nav buttons (extracted to avoid duplication between card types) ─── */
function NavButtons({
  currentCardIndex, maxReachedIndex, isLastCard, isLastCardOfNonFinalChunk,
  canProceed, loading, nextChunkInFlight, nextChunkCards,
  onPrev, onNext, onNextChunk, onFinish, remediationMode, chunkQuestions, isSubmitting, t,
}) {
  // Determine which primary action to show on the right side
  const showNextSection = isLastCardOfNonFinalChunk && canProceed;
  const showFinish = isLastCard && canProceed;
  const showNextCard = !showNextSection && !showFinish;

  const prevDisabled = currentCardIndex === 0;
  const nextSectionDisabled = nextChunkInFlight && !nextChunkCards;
  const finishDisabled = loading;
  const nextCardActive = currentCardIndex < maxReachedIndex || (canProceed && !isLastCard);
  const nextCardDisabled = isSubmitting || (currentCardIndex < maxReachedIndex ? false : (!canProceed || isLastCard));

  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "1rem", gap: "0.5rem" }}>
      <button
        onClick={onPrev}
        disabled={prevDisabled}
        style={{
          display: "flex",
          alignItems: "center",
          gap: "6px",
          padding: "0.75rem 1.25rem",
          borderRadius: "12px",
          border: "2px solid var(--color-border)",
          backgroundColor: "var(--color-surface)",
          fontWeight: 600,
          fontSize: "0.9rem",
          fontFamily: "inherit",
          color: prevDisabled ? "var(--color-text-muted)" : "var(--color-text)",
          cursor: prevDisabled ? "not-allowed" : "pointer",
          opacity: prevDisabled ? 0.5 : 1,
        }}
      >
        <ChevronLeft size={18} /> {t("learning.previous")}
      </button>

      {showNextSection && (
        <button
          onClick={onNextChunk}
          disabled={nextSectionDisabled}
          style={{
            display: "flex",
            alignItems: "center",
            gap: "6px",
            padding: "0.75rem 1.25rem",
            borderRadius: "12px",
            border: "none",
            fontWeight: 700,
            fontSize: "0.95rem",
            fontFamily: "inherit",
            backgroundColor: nextSectionDisabled ? "var(--color-border)" : "var(--color-primary)",
            color: nextSectionDisabled ? "var(--color-text-muted)" : "#ffffff",
            cursor: nextSectionDisabled ? "not-allowed" : "pointer",
          }}
        >
          {nextChunkInFlight && !nextChunkCards ? (
            <>
              <Loader size={18} style={{ animation: "spin 1s linear infinite" }} />
              {t("chunk.loadingNext")}
            </>
          ) : (
            chunkQuestions?.length > 0
              ? <><Flag size={18} style={{ marginRight: "0.3rem" }} />{t("learning.answerQuestions", "Answer Questions")}</>
              : <>{t("learning.nextSection")} <ChevronRight size={18} /></>
          )}
        </button>
      )}

      {showFinish && (
        <button
          onClick={onFinish}
          disabled={finishDisabled}
          style={{
            display: "flex",
            alignItems: "center",
            gap: "6px",
            padding: "0.75rem 1.5rem",
            borderRadius: "12px",
            border: "none",
            color: "#ffffff",
            fontWeight: 700,
            fontSize: "0.95rem",
            fontFamily: "inherit",
            backgroundColor: finishDisabled ? "var(--color-border)" : "#22C55E",
            cursor: finishDisabled ? "not-allowed" : "pointer",
            boxShadow: finishDisabled ? "none" : "0 4px 12px rgba(34,197,94,0.3)",
          }}
        >
          {loading ? (
            <>
              <Loader size={18} style={{ animation: "spin 1s linear infinite" }} />
              {t("learning.startingChat")}
            </>
          ) : (
            <>
              <Flag size={18} />
              {t("learning.finishCards")}
            </>
          )}
        </button>
      )}

      {showNextCard && (
        <button
          onClick={onNext}
          disabled={nextCardDisabled}
          style={{
            display: "flex",
            alignItems: "center",
            gap: "6px",
            padding: "0.75rem 1.25rem",
            borderRadius: "12px",
            border: "none",
            fontWeight: 600,
            fontSize: "0.9rem",
            fontFamily: "inherit",
            backgroundColor: nextCardActive ? "var(--color-primary-dark, #EA580C)" : "var(--color-border)",
            color: nextCardActive ? "#ffffff" : "var(--color-text-muted)",
            cursor: nextCardDisabled ? "not-allowed" : "pointer",
            opacity: isSubmitting ? 0.6 : 1,
            pointerEvents: isSubmitting ? "none" : "auto",
          }}
        >
          {t("learning.next")} <ChevronRight size={18} />
        </button>
      )}
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
          ? "color-mix(in srgb, var(--color-success, #22c55e) 5%, var(--color-bg))"
          : answered && !feedback?.correct
          ? "color-mix(in srgb, var(--color-danger, #ef4444) 5%, var(--color-bg))"
          : "var(--color-bg)",
        animation: answered && !feedback?.correct ? "shake 0.35s ease-out" : "none",
      }}
    >
      <div style={{ fontSize: "15px", fontWeight: 600, color: "#0F172A", marginBottom: "12px", lineHeight: 1.5 }}>
        <span style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: "24px", height: "24px", borderRadius: "50%", backgroundColor: "#EA580C", color: "#FFFFFF", fontSize: "12px", fontWeight: 800, marginRight: "8px", flexShrink: 0 }}>
          {index}
        </span>
        <ReactMarkdown
          remarkPlugins={[remarkMath]}
          rehypePlugins={[rehypeKatex]}
          components={{ p: ({ children }) => <span>{children}</span> }}
          skipHtml={true}
        >
          {question.question}
        </ReactMarkdown>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
        {question.options.map((opt, oi) => {
          const isSelected = answered && feedback?.answer === oi;
          const optIsCorrect = oi === question.correct_index;
          const showCorrect = answered && optIsCorrect;
          const showWrong = isSelected && !feedback?.correct;

          let borderColor = "var(--color-border)";
          let bgColor = "var(--color-surface)";
          let textColor = "var(--color-text)";

          if (showCorrect) { borderColor = "var(--color-success, #22c55e)"; bgColor = "color-mix(in srgb, var(--color-success, #22c55e) 10%, transparent)"; textColor = "var(--color-success-dark, #166534)"; }
          else if (showWrong) { borderColor = "var(--color-danger, #ef4444)"; bgColor = "color-mix(in srgb, var(--color-danger, #ef4444) 10%, transparent)"; textColor = "var(--color-danger-dark, #991b1b)"; }

          return (
            <button
              key={oi}
              onClick={() => onAnswer(oi)}
              disabled={isLocked}
              aria-label={t("aria.mcqOption", { label: String.fromCharCode(65 + oi) })}
              style={{
                display: "flex", alignItems: "center", gap: "0.75rem",
                width: "100%", padding: "0.75rem 1rem",
                borderRadius: "9999px",
                border: `2px solid ${borderColor}`,
                backgroundColor: bgColor, color: textColor,
                fontSize: "0.9rem",
                fontWeight: isSelected || showCorrect ? 700 : 500,
                cursor: isLocked ? "default" : "pointer",
                fontFamily: "inherit", textAlign: "left",
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
              <span
                style={{
                  width: "28px", height: "28px", borderRadius: "50%",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  flexShrink: 0, fontSize: "0.75rem", fontWeight: 700,
                  backgroundColor: showCorrect ? "var(--color-success, #22c55e)" : showWrong ? "var(--color-danger, #ef4444)" : "color-mix(in srgb, var(--color-primary) 10%, var(--color-surface))",
                  color: showCorrect || showWrong ? "#fff" : "var(--color-primary)",
                }}
              >
                {showCorrect ? <CheckCircle size={14} /> : showWrong ? <XCircle size={14} /> : String.fromCharCode(65 + oi)}
              </span>
              <ReactMarkdown
                remarkPlugins={[remarkMath]}
                rehypePlugins={[rehypeKatex]}
                components={{ p: ({ children }) => <span>{children}</span> }}
                skipHtml={true}
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
            marginTop: "0.625rem",
            padding: "0.5rem 0.75rem",
            borderRadius: "8px",
            fontSize: "0.85rem",
            lineHeight: 1.4,
            color: "var(--color-text)",
            backgroundColor: feedback.correct
              ? "color-mix(in srgb, var(--color-success, #22c55e) 8%, transparent)"
              : "color-mix(in srgb, var(--color-danger, #ef4444) 8%, transparent)",
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
