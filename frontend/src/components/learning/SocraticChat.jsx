import { useState, useRef, useEffect, useLayoutEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useSession } from "../../context/SessionContext";
import ChatBubble from "./ChatBubble";
import ConceptImage from "./ConceptImage";
import { Send, Brain, Image as ImageIcon, ChevronDown, ChevronUp } from "lucide-react";
import { trackEvent } from "../../utils/analytics";

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

export default function SocraticChat() {
  const { t } = useTranslation();
  const { messages, sendAnswer, checkLoading: loading, conceptTitle, session, cards } = useSession();
  const [input, setInput] = useState("");
  const messagesEndRef = useRef(null);
  const textareaRef = useRef(null);

  const usefulDiagrams = useMemo(() => {
    const seen = new Set();
    const diagrams = [];
    (cards || []).forEach((card) => {
      (card.images || []).forEach((img) => {
        const key = img.url || img.filename;
        if (!seen.has(key)) {
          seen.add(key);
          diagrams.push(img);
        }
      });
    });
    return diagrams;
  }, [cards]);

  useLayoutEffect(() => {
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
    sendAnswer(trimmed);
    setInput("");
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

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
        background: "linear-gradient(135deg, var(--color-accent), var(--color-primary))",
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
          <Brain size={20} color="#fff" aria-hidden="true" />
        </div>
        <div>
          <div style={{ color: "#fff", fontWeight: 700, fontSize: "1.05rem" }}>
            {t("chat.practiceChat")}
          </div>
          <div style={{ color: "rgba(255,255,255,0.8)", fontSize: "0.8rem" }}>
            {t("chat.chatSubtitle", { title: conceptTitle })}
          </div>
        </div>
      </div>

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
        {usefulDiagrams.length > 0 && (
          <DiagramPanel diagrams={usefulDiagrams} conceptTitle={conceptTitle} />
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
          <ChatBubble key={idx} role={msg.role} content={msg.content} />
        ))}

        {loading && <TypingDots />}

        <div ref={messagesEndRef} />
      </div>

      {/* Input — fixed at bottom */}
      <div style={{
        padding: "0.875rem 1.25rem",
        borderTop: "2px solid var(--color-border)",
        backgroundColor: "var(--color-surface)",
        flexShrink: 0,
      }}>
        <form onSubmit={handleSubmit} style={{ display: "flex", gap: "0.5rem", alignItems: "flex-end" }}>
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={t("chat.inputPlaceholder")}
            disabled={loading}
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
            disabled={!input.trim() || loading}
            aria-label="Send answer"
            style={{
              display: "flex", alignItems: "center", justifyContent: "center",
              width: "44px", height: "44px", flexShrink: 0,
              borderRadius: "var(--radius-md)", border: "none",
              backgroundColor: input.trim() && !loading ? "var(--color-primary)" : "var(--color-border)",
              color: input.trim() && !loading ? "#fff" : "var(--color-text-muted)",
              cursor: input.trim() && !loading ? "pointer" : "not-allowed",
              transition: "all var(--motion-fast)",
            }}
          >
            <Send size={18} aria-hidden="true" />
          </button>
        </form>
        <p style={{ fontSize: "0.7rem", color: "var(--color-text-muted)", marginTop: "0.35rem", paddingLeft: "0.25rem" }}>
          Enter to send · Shift+Enter for new line
        </p>
      </div>
    </div>
  );
}

function DiagramPanel({ diagrams, conceptTitle }) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);

  return (
    <div style={{
      marginBottom: "0.75rem",
      borderRadius: "var(--radius-md)",
      border: "1.5px solid var(--color-border)",
      backgroundColor: "var(--color-surface)",
      overflow: "hidden",
    }}>
      <button
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
        style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          width: "100%", padding: "0.6rem 1rem",
          border: "none", backgroundColor: "transparent",
          color: "var(--color-text-muted)", fontSize: "0.8rem", fontWeight: 700,
          cursor: "pointer", fontFamily: "inherit",
        }}
      >
        <span style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
          <ImageIcon size={14} aria-hidden="true" />
          {t("chat.refDiagrams", { count: diagrams.length })}
        </span>
        {expanded ? <ChevronUp size={14} aria-hidden="true" /> : <ChevronDown size={14} aria-hidden="true" />}
      </button>
      {expanded && (
        <div style={{ padding: "0.5rem 1rem 0.75rem" }}>
          {diagrams.map((img, i) => (
            <ConceptImage key={i} img={img} maxWidth="400px" />
          ))}
        </div>
      )}
    </div>
  );
}
