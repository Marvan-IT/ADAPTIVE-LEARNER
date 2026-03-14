import React, { useState, useRef, useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useSession } from "../../context/SessionContext";
import ChatBubble from "./ChatBubble";
import ConceptImage from "./ConceptImage";
import { Send, Brain, Target } from "lucide-react";
import { trackEvent } from "../../utils/analytics";
import { useNavigate } from "react-router-dom";

// Boredom detection — runs client-side, signals forwarded to backend
const BOREDOM_PHRASES = new Set([
  "ok", "okay", "sure", "k", "next", "boring", "bored",
  "i know", "i know this", "i already know", "easy",
  "yep", "yup", "yeah", "fine", "whatever", "skip",
  "got it", "understood", "ugh", "meh",
]);

const detectBoredomSignal = (text) => {
  const t = text.trim().toLowerCase();
  if (BOREDOM_PHRASES.has(t)) return "boredom_explicit";
  if (t.length > 0 && t.length < 15) return "short_response";
  return null;
};

function TypingDots() {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: "4px", padding: "0.75rem 0" }} aria-label="ADA is thinking">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          style={{
            width: "8px",
            height: "8px",
            borderRadius: "50%",
            backgroundColor: "var(--color-primary)",
            animation: `dots-bounce 1.2s ${i * 0.2}s infinite ease-in-out`,
          }}
        />
      ))}
    </div>
  );
}

/* ─── Score announcement banner shown after check_complete ─── */
function ScoreAnnouncement({ score, passed, remediationNeeded, onContinueToReview, sessionId, loadRemediationCards }) {
  const navigate = useNavigate();

  if (passed) {
    return (
      <div style={{
        margin: "0.75rem 0",
        padding: "0.75rem 1rem",
        borderRadius: "var(--radius-md)",
        backgroundColor: "rgba(34,197,94,0.1)",
        border: "1.5px solid #22c55e",
        display: "flex",
        alignItems: "center",
        gap: "0.6rem",
        fontSize: "0.92rem",
        fontWeight: 700,
        color: "#166534",
      }}>
        <span aria-hidden="true">✅</span>
        Score: {score}% — You passed!
      </div>
    );
  }

  if (remediationNeeded) {
    return (
      <div style={{
        margin: "0.75rem 0",
        display: "flex",
        flexDirection: "column",
        gap: "0.6rem",
      }}>
        <div style={{
          padding: "0.75rem 1rem",
          borderRadius: "var(--radius-md)",
          backgroundColor: "rgba(245,158,11,0.1)",
          border: "1.5px solid #f59e0b",
          display: "flex",
          alignItems: "center",
          gap: "0.6rem",
          fontSize: "0.92rem",
          fontWeight: 700,
          color: "#92400e",
        }}>
          <span aria-hidden="true">📊</span>
          Score: {score}% — Let's review those parts!
        </div>
        <button
          onClick={() => loadRemediationCards(sessionId)}
          style={{
            padding: "0.65rem 1.25rem",
            borderRadius: "var(--radius-md)",
            border: "none",
            backgroundColor: "#f59e0b",
            color: "#fff",
            fontWeight: 700,
            fontSize: "0.9rem",
            cursor: "pointer",
            fontFamily: "inherit",
            alignSelf: "flex-start",
          }}
        >
          Continue to Review →
        </button>
      </div>
    );
  }

  // All attempts exhausted
  return (
    <div style={{
      margin: "0.75rem 0",
      display: "flex",
      flexDirection: "column",
      gap: "0.75rem",
    }}>
      <div style={{
        padding: "0.75rem 1rem",
        borderRadius: "var(--radius-md)",
        backgroundColor: "color-mix(in srgb, var(--color-text-muted) 8%, var(--color-surface))",
        border: "1.5px solid var(--color-border)",
        fontSize: "0.92rem",
        color: "var(--color-text-muted)",
        lineHeight: 1.5,
      }}>
        You gave it your absolute best — score: <strong>{score}%</strong>. You can return to this concept from the map whenever you're ready to try again.
      </div>
      <button
        onClick={() => navigate("/map")}
        style={{
          padding: "0.65rem 1.25rem",
          borderRadius: "var(--radius-md)",
          border: "none",
          backgroundColor: "var(--color-primary)",
          color: "#fff",
          fontWeight: 700,
          fontSize: "0.9rem",
          cursor: "pointer",
          fontFamily: "inherit",
          alignSelf: "flex-start",
        }}
      >
        Back to Concept Map
      </button>
    </div>
  );
}

export default function SocraticChat({ recheckMode = false }) {
  const { t } = useTranslation();
  const {
    messages,
    sendAnswer,
    checkLoading: loading,
    conceptTitle,
    session,
    checkScore,
    checkPassed,
    remediationNeeded,
    phase,
    loadRemediationCards,
  } = useSession();

  const [input, setInput] = useState("");
  const messagesEndRef = useRef(null);
  const textareaRef = useRef(null);

  // Count user messages for progress indicator
  const userMessageCount = useMemo(
    () => messages.filter((m) => m.role === "user").length,
    [messages]
  );

  // Determine if last message completed the check
  const lastCheckComplete = useMemo(() => {
    // We detect this from context state: if checkScore is set and chat loading just finished,
    // we consider the check complete. Use phase to determine.
    const checkDonePhases = ["COMPLETED", "REMEDIATING", "REMEDIATING_2", "ATTEMPTS_EXHAUSTED"];
    return checkDonePhases.includes(phase) && checkScore !== null;
  }, [phase, checkScore]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  useEffect(() => {
    if (!loading && textareaRef.current) {
      textareaRef.current.focus();
    }
  }, [loading]);

  const handleSubmit = (e) => {
    e.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || loading) return;
    trackEvent("socratic_answer_sent", {
      exchange_count: messages.length,
      message_length: trimmed.length,
      concept_id: session?.concept_id,
      concept_title: conceptTitle,
    });
    const boredSignal = detectBoredomSignal(trimmed);
    sendAnswer(trimmed, boredSignal);
    setInput("");
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  // Determine if input should be disabled — after check completes we stop accepting answers
  const inputDisabled = loading || lastCheckComplete;

  return (
    <div style={{
      backgroundColor: "var(--color-surface)",
      borderRadius: "var(--radius-lg)",
      border: "2px solid var(--color-border)",
      overflow: "hidden",
      display: "flex",
      flexDirection: "column",
      boxShadow: "var(--shadow-md)",
    }}>
      {/* Header */}
      <div style={{
        background: recheckMode
          ? "linear-gradient(135deg, #0d9488, #0891b2)"
          : "linear-gradient(135deg, var(--color-accent), var(--color-primary))",
        padding: "1rem 1.5rem",
        display: "flex",
        alignItems: "center",
        gap: "0.75rem",
        flexShrink: 0,
      }}>
        <div style={{
          width: "40px", height: "40px", borderRadius: "50%",
          backgroundColor: "rgba(255,255,255,0.2)",
          display: "flex", alignItems: "center", justifyContent: "center",
        }}>
          {recheckMode
            ? <Target size={20} color="#fff" aria-hidden="true" />
            : <Brain size={20} color="#fff" aria-hidden="true" />
          }
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ color: "#fff", fontWeight: 700, fontSize: "1.05rem" }}>
            {recheckMode ? "Let's try those topics again!" : t("chat.practiceChat")}
          </div>
          <div style={{ color: "rgba(255,255,255,0.8)", fontSize: "0.8rem" }}>
            {t("chat.chatSubtitle", { title: conceptTitle })}
          </div>
        </div>

        {/* Question progress pill */}
        {userMessageCount > 0 && (
          <div style={{
            padding: "0.2rem 0.65rem",
            borderRadius: "9999px",
            backgroundColor: "rgba(255,255,255,0.2)",
            color: "#fff",
            fontSize: "0.75rem",
            fontWeight: 700,
            flexShrink: 0,
          }}>
            Q{userMessageCount}
          </div>
        )}
      </div>

      {/* Recheck mode banner */}
      {recheckMode && (
        <div style={{
          padding: "0.5rem 1.25rem",
          backgroundColor: "rgba(13,148,136,0.08)",
          borderBottom: "1px solid rgba(13,148,136,0.2)",
          fontSize: "0.82rem",
          color: "#0d9488",
          fontWeight: 600,
          display: "flex",
          alignItems: "center",
          gap: "0.4rem",
        }}>
          <span aria-hidden="true">🎯</span>
          Let's try those topics again!
        </div>
      )}

      {/* Progress indicator bar */}
      {userMessageCount > 0 && (
        <div style={{
          height: "3px",
          backgroundColor: "var(--color-border)",
          flexShrink: 0,
          position: "relative",
          overflow: "hidden",
        }}>
          <div style={{
            position: "absolute",
            left: 0, top: 0, bottom: 0,
            width: `${Math.min(userMessageCount * 20, 100)}%`,
            backgroundColor: recheckMode ? "#0d9488" : "var(--color-primary)",
            transition: "width 0.4s ease",
          }} />
        </div>
      )}

      {/* Messages — scrollable */}
      <div
        role="log"
        aria-live="polite"
        aria-label="Chat messages"
        style={{
          padding: "1.25rem 1.5rem",
          minHeight: "300px",
          maxHeight: "calc(100vh - 380px)",
          overflowY: "auto",
          backgroundColor: "var(--color-bg)",
          flexGrow: 1,
        }}
      >
        {/* Question counter chip at top of messages */}
        {userMessageCount > 0 && (
          <div style={{
            display: "flex",
            justifyContent: "center",
            marginBottom: "0.75rem",
          }}>
            <span style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "0.3rem",
              padding: "0.2rem 0.75rem",
              borderRadius: "9999px",
              backgroundColor: "var(--color-surface)",
              border: "1px solid var(--color-border)",
              fontSize: "0.75rem",
              color: "var(--color-text-muted)",
              fontWeight: 600,
            }}>
              Question {userMessageCount}
            </span>
          </div>
        )}

        {messages.length === 0 && !loading && (
          <div style={{
            textAlign: "center", padding: "2rem",
            color: "var(--color-text-muted)", fontSize: "0.95rem",
          }}>
            <Brain size={32} style={{ marginBottom: "0.5rem", opacity: 0.4 }} aria-hidden="true" />
            <p>{t("chat.preparingQuestion")}</p>
          </div>
        )}

        {messages.map((msg, idx) => (
          <React.Fragment key={idx}>
            <ChatBubble role={msg.role} content={msg.content} />
            {msg.role === "assistant" && msg.image && (
              <div style={{ marginBottom: "0.75rem", marginLeft: "0.5rem" }}>
                <ConceptImage img={msg.image} maxWidth="340px" />
              </div>
            )}
          </React.Fragment>
        ))}

        {loading && <TypingDots />}

        {/* Score announcement after check complete */}
        {lastCheckComplete && !loading && (
          <ScoreAnnouncement
            score={checkScore}
            passed={checkPassed === true}
            remediationNeeded={remediationNeeded}
            sessionId={session?.id}
            loadRemediationCards={loadRemediationCards}
          />
        )}

        <div ref={messagesEndRef} style={{ height: "1px" }} />
      </div>

      {/* Input — fixed at bottom */}
      <div style={{
        padding: "0.875rem 1.25rem",
        borderTop: "2px solid var(--color-border)",
        backgroundColor: "var(--color-surface)",
        flexShrink: 0,
      }}>
        {inputDisabled && lastCheckComplete ? (
          <p style={{
            textAlign: "center",
            color: "var(--color-text-muted)",
            fontSize: "0.85rem",
            padding: "0.4rem 0",
            fontStyle: "italic",
          }}>
            {checkPassed ? "Well done! Moving on..." : remediationNeeded ? "See the review cards above." : "Session complete."}
          </p>
        ) : (
          <>
            <form onSubmit={handleSubmit} style={{ display: "flex", gap: "0.5rem", alignItems: "flex-end" }}>
              <textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={t("chat.inputPlaceholder")}
                disabled={inputDisabled}
                maxLength={2000}
                rows={1}
                style={{
                  flex: 1,
                  padding: "0.7rem 1rem",
                  fontSize: "0.95rem",
                  borderRadius: "var(--radius-md)",
                  border: "2px solid var(--color-border)",
                  backgroundColor: "var(--color-bg)",
                  color: "var(--color-text)",
                  fontFamily: "inherit",
                  outline: "none",
                  resize: "none",
                  minHeight: "44px",
                  maxHeight: "120px",
                  overflowY: "auto",
                  transition: "border-color var(--motion-fast)",
                  lineHeight: 1.5,
                }}
                onFocus={(e) => (e.target.style.borderColor = "var(--color-primary)")}
                onBlur={(e) => (e.target.style.borderColor = "var(--color-border)")}
              />
              <button
                type="submit"
                disabled={!input.trim() || inputDisabled}
                aria-label="Send answer"
                style={{
                  display: "flex", alignItems: "center", justifyContent: "center",
                  width: "44px", height: "44px", flexShrink: 0,
                  borderRadius: "var(--radius-md)", border: "none",
                  backgroundColor: input.trim() && !inputDisabled ? "var(--color-primary)" : "var(--color-border)",
                  color: input.trim() && !inputDisabled ? "#fff" : "var(--color-text-muted)",
                  cursor: input.trim() && !inputDisabled ? "pointer" : "not-allowed",
                  transition: "all var(--motion-fast)",
                }}
              >
                <Send size={18} aria-hidden="true" />
              </button>
            </form>
            <p style={{ fontSize: "0.7rem", color: "var(--color-text-muted)", marginTop: "0.35rem", paddingLeft: "0.25rem" }}>
              Enter to send · Shift+Enter for new line
            </p>
          </>
        )}
      </div>
    </div>
  );
}

