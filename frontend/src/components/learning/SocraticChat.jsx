import { useState, useRef, useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useSession } from "../../context/SessionContext";
import ChatBubble from "./ChatBubble";
import ConceptImage from "./ConceptImage";
import { Send, Loader, MessageCircle, Brain, Image as ImageIcon, ChevronDown, ChevronUp } from "lucide-react";
import { trackEvent } from "../../utils/analytics";

export default function SocraticChat() {
  const { t } = useTranslation();
  const { messages, sendAnswer, checkLoading: loading, conceptTitle, session, cards } = useSession();
  const [input, setInput] = useState("");
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);

  // Collect unique diagrams from all cards for reference panel
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

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Focus input after AI responds
  useEffect(() => {
    if (!loading && inputRef.current) {
      inputRef.current.focus();
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

  return (
    <div style={{
      backgroundColor: "var(--color-surface)",
      borderRadius: "16px",
      border: "2px solid var(--color-border)",
      overflow: "hidden",
    }}>
      {/* ─── Chat Header ─── */}
      <div style={{
        background: "linear-gradient(135deg, var(--color-accent), var(--color-primary))",
        padding: "1rem 1.5rem",
        display: "flex",
        alignItems: "center",
        gap: "0.75rem",
      }}>
        <div style={{
          width: "40px", height: "40px", borderRadius: "50%",
          backgroundColor: "rgba(255,255,255,0.2)",
          display: "flex", alignItems: "center", justifyContent: "center",
        }}>
          <MessageCircle size={20} color="#fff" />
        </div>
        <div>
          <div style={{
            color: "#fff", fontWeight: 700, fontSize: "1.05rem",
          }}>
            {t("chat.practiceChat")}
          </div>
          <div style={{
            color: "rgba(255,255,255,0.8)", fontSize: "0.8rem", fontWeight: 500,
          }}>
            {t("chat.chatSubtitle", { title: conceptTitle })}
          </div>
        </div>
      </div>

      {/* ─── Messages Area ─── */}
      <div style={{
        padding: "1.25rem 1.5rem",
        minHeight: "300px",
        maxHeight: "calc(100vh - 380px)",
        overflowY: "auto",
        backgroundColor: "var(--color-bg)",
      }}>
        {/* ─── Reference Diagrams (collapsible) ─── */}
        {usefulDiagrams.length > 0 && (
          <DiagramPanel diagrams={usefulDiagrams} conceptTitle={conceptTitle} />
        )}

        {messages.length === 0 && !loading && (
          <div style={{
            textAlign: "center", padding: "2rem",
            color: "var(--color-text-muted)", fontSize: "0.95rem",
          }}>
            <Brain size={32} style={{ marginBottom: "0.5rem", opacity: 0.5 }} />
            <p>{t("chat.preparingQuestion")}</p>
          </div>
        )}

        {messages.map((msg, idx) => (
          <ChatBubble key={idx} role={msg.role} content={msg.content} />
        ))}

        {loading && (
          <div style={{
            display: "flex", alignItems: "center", gap: "0.5rem",
            color: "var(--color-text-muted)", fontSize: "0.9rem",
            padding: "0.75rem 0",
          }}>
            <Loader size={16} style={{ animation: "spin 1s linear infinite" }} />
            {t("chat.readingAnswer")}
            <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* ─── Input Area ─── */}
      <div style={{
        padding: "1rem 1.5rem",
        borderTop: "2px solid var(--color-border)",
        backgroundColor: "var(--color-surface)",
      }}>
        <form onSubmit={handleSubmit} style={{ display: "flex", gap: "0.5rem" }}>
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={t("chat.inputPlaceholder")}
            disabled={loading}
            maxLength={2000}
            style={{
              flex: 1,
              padding: "0.8rem 1rem",
              fontSize: "1rem",
              borderRadius: "12px",
              border: "2px solid var(--color-border)",
              backgroundColor: "var(--color-bg)",
              color: "var(--color-text)",
              fontFamily: "inherit",
              outline: "none",
              transition: "border-color 0.2s",
            }}
            onFocus={(e) => (e.target.style.borderColor = "var(--color-primary)")}
            onBlur={(e) => (e.target.style.borderColor = "var(--color-border)")}
          />
          <button
            type="submit"
            disabled={!input.trim() || loading}
            style={{
              display: "flex", alignItems: "center", justifyContent: "center",
              width: "48px", height: "48px",
              borderRadius: "12px", border: "none",
              backgroundColor: input.trim() && !loading ? "var(--color-primary)" : "var(--color-border)",
              color: input.trim() && !loading ? "#fff" : "var(--color-text-muted)",
              cursor: input.trim() && !loading ? "pointer" : "not-allowed",
              transition: "all 0.2s",
              flexShrink: 0,
            }}
          >
            <Send size={20} />
          </button>
        </form>
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
      borderRadius: "10px",
      border: "1.5px solid var(--color-border)",
      backgroundColor: "var(--color-surface)",
      overflow: "hidden",
    }}>
      <button
        onClick={() => setExpanded(!expanded)}
        style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          width: "100%", padding: "0.6rem 1rem",
          border: "none", backgroundColor: "transparent",
          color: "var(--color-text-muted)", fontSize: "0.8rem", fontWeight: 700,
          cursor: "pointer", fontFamily: "inherit",
        }}
      >
        <span style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
          <ImageIcon size={14} />
          {t("chat.refDiagrams", { count: diagrams.length })}
        </span>
        {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>
      {expanded && (
        <div style={{ padding: "0.5rem 1rem 0.75rem" }}>
          {diagrams.slice(0, 5).map((img, i) => (
            <ConceptImage key={i} img={img} maxWidth="400px" />
          ))}
        </div>
      )}
    </div>
  );
}
