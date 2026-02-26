import { useState, useMemo, useEffect, useCallback, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { useSession } from "../../context/SessionContext";
import { API_BASE_URL } from "../../utils/constants";
import AssistantPanel from "./AssistantPanel";
import { useTranslation } from "react-i18next";
import { trackEvent } from "../../utils/analytics";
import {
  ChevronLeft,
  ChevronRight,
  CheckCircle,
  XCircle,
  BookOpen,
  Flag,
  Loader,
} from "lucide-react";

const WRONG_FEEDBACK_MS = 1800;

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
  } = useSession();

  const card = cards[currentCardIndex];
  const isLastCard = currentCardIndex === cards.length - 1;

  // Per-card question state: { mcqIdx, tfIdx, mcqCorrect, tfCorrect, mcqFeedback, tfFeedback }
  const [cardStates, setCardStates] = useState({});
  const feedbackTimerRef = useRef(null);

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

      updateCardState(currentCardIndex, {
        mcqFeedback: { correct, explanation: q.explanation, answer: optionIndex },
        ...(correct ? { mcqCorrect: true } : {}),
      });

      if (!correct) {
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

      updateCardState(currentCardIndex, {
        tfFeedback: { correct, explanation: q.explanation, answer: value },
        ...(correct ? { tfCorrect: true } : {}),
      });

      if (!correct) {
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

  if (!card) return null;

  return (
    <div style={{ display: "flex", gap: "1rem", alignItems: "flex-start" }}>
      {/* ─── Main Card Area (70%) ─── */}
      <div style={{ flex: "1 1 0", minWidth: 0 }}>
        <CardProgress current={currentCardIndex} total={cards.length} cardStates={cardStates} cards={cards} />

        {/* Card Content */}
        <div
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
            <div>
              <div style={{ color: "#fff", fontWeight: 700, fontSize: "1.05rem" }}>
                {card.title}
              </div>
              <div style={{ color: "rgba(255,255,255,0.8)", fontSize: "0.78rem", fontWeight: 500 }}>
                {conceptTitle} — {t("learning.cardProgress", { current: currentCardIndex + 1, total: cards.length })}
              </div>
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
            {card.images?.length > 0 && (
              <div style={{ marginTop: "1rem" }}>
                {card.images.map((img, i) => (
                  <div
                    key={i}
                    style={{
                      borderRadius: "10px",
                      border: "1.5px solid var(--color-border)",
                      overflow: "hidden",
                      backgroundColor: "#fff",
                      marginBottom: "0.75rem",
                      maxWidth: "500px",
                    }}
                  >
                    <img
                      src={`${API_BASE_URL}${img.url}`}
                      alt={img.caption || `Diagram ${i + 1}`}
                      style={{ width: "100%", height: "auto", display: "block" }}
                      loading="lazy"
                    />
                    {img.caption && (
                      <div
                        style={{
                          padding: "0.4rem 0.7rem",
                          fontSize: "0.8rem",
                          color: "var(--color-text-muted)",
                          fontStyle: "italic",
                          lineHeight: 1.3,
                          borderTop: "1px solid var(--color-border)",
                          backgroundColor: "var(--color-bg)",
                        }}
                      >
                        {img.caption}
                      </div>
                    )}
                  </div>
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
              onClick={finishCards}
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
              onClick={goToNextCard}
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

      {/* ─── Assistant Panel (30%) ─── */}
      <div style={{ width: "320px", flexShrink: 0 }}>
        <AssistantPanel />
      </div>

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

/* ─── Card Progress Dots ─── */
function CardProgress({ current, total, cardStates, cards }) {
  const { t } = useTranslation();

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: "0.3rem",
        marginBottom: "1rem",
      }}
    >
      {cards.map((card, idx) => {
        const cs = cardStates[idx];
        const isDone = cs?.mcqCorrect && cs?.tfCorrect;
        const isCurrent = idx === current;

        return (
          <div key={idx} style={{ display: "flex", alignItems: "center", gap: "0.3rem" }}>
            {idx > 0 && (
              <div
                style={{
                  width: "20px",
                  height: "2px",
                  backgroundColor: isDone ? "var(--color-success)" : "var(--color-border)",
                  borderRadius: "1px",
                }}
              />
            )}
            <div
              style={{
                width: isCurrent ? "28px" : "12px",
                height: "12px",
                borderRadius: isCurrent ? "6px" : "50%",
                backgroundColor: isDone
                  ? "var(--color-success)"
                  : isCurrent
                  ? "var(--color-primary)"
                  : "var(--color-border)",
                transition: "all 0.3s",
              }}
            />
          </div>
        );
      })}
      <span
        style={{
          marginLeft: "0.75rem",
          fontSize: "0.8rem",
          fontWeight: 700,
          color: "var(--color-text-muted)",
        }}
      >
        {t("learning.cardProgress", { current: current + 1, total })}
      </span>
    </div>
  );
}

/* ─── MCQ Question Block ─── */
function MCQBlock({ question, index, feedback, isCorrect, onAnswer }) {
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

      <div style={{ display: "flex", flexDirection: "column", gap: "0.4rem" }}>
        {question.options.map((opt, oi) => {
          const isSelected = answered && feedback?.answer === oi;
          const optIsCorrect = oi === question.correct_index;
          const showCorrect = answered && optIsCorrect;
          const showWrong = isSelected && !feedback?.correct;

          return (
            <button
              key={oi}
              onClick={() => onAnswer(oi)}
              disabled={isLocked}
              style={{
                display: "flex",
                alignItems: "center",
                gap: "0.5rem",
                padding: "0.6rem 0.9rem",
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
                fontSize: "0.9rem",
                fontWeight: isSelected || showCorrect ? 700 : 500,
                cursor: isLocked ? "default" : "pointer",
                fontFamily: "inherit",
                textAlign: "left",
                transition: "all 0.2s",
              }}
            >
              <span
                style={{
                  width: "22px",
                  height: "22px",
                  borderRadius: "50%",
                  border: `2px solid ${
                    showCorrect ? "var(--color-success)" : showWrong ? "var(--color-danger)" : "var(--color-border)"
                  }`,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  flexShrink: 0,
                  fontSize: "0.7rem",
                  fontWeight: 800,
                  backgroundColor: showCorrect ? "var(--color-success)" : showWrong ? "var(--color-danger)" : "transparent",
                  color: showCorrect || showWrong ? "#fff" : "var(--color-text-muted)",
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
