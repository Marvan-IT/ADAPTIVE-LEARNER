import { useState, useRef, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { useSession } from "../../context/SessionContext";
import { Brain, Send, Sparkles } from "lucide-react";
import { trackEvent } from "../../utils/analytics";
import { AnimatePresence, motion } from "framer-motion";
import { useAdaptiveStore } from "../../store/adaptiveStore";

const IDLE_TIMEOUT_MS = 90000; // 90 seconds
const MAX_IDLE_TRIGGERS_PER_CARD = 2;

const modeColors = {
  NORMAL:     "linear-gradient(135deg, var(--color-accent), var(--color-primary))",
  FAST:       "linear-gradient(135deg, var(--xp-gold), #f97316)",
  SLOW:       "linear-gradient(135deg, var(--adapt-slow), var(--color-primary-dark))",
  STRUGGLING: "linear-gradient(135deg, var(--adapt-struggling), #fb923c)",
  BORED:      "linear-gradient(135deg, var(--adapt-bored), #06b6d4)",
};

export default function AssistantPanel() {
  const { t } = useTranslation();
  const {
    assistMessages,
    assistLoading,
    sendAssistMessage,
    currentCardIndex,
    cards,
    conceptTitle,
    session,
  } = useSession();

  const mode = useAdaptiveStore((s) => s.mode);

  const [input, setInput] = useState("");
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);
  const idleTimerRef = useRef(null);
  const lastInteractionRef = useRef(Date.now());
  const idleTriggersRef = useRef(0);

  // Auto-scroll on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [assistMessages]);

  // Focus input after assistant responds
  useEffect(() => {
    if (!assistLoading && inputRef.current) {
      inputRef.current.focus();
    }
  }, [assistLoading]);

  // Reset interaction timestamp on card change or answer
  const resetIdle = useCallback(() => {
    lastInteractionRef.current = Date.now();
  }, []);

  useEffect(() => {
    resetIdle();
  }, [assistMessages, resetIdle]);

  // Reset idle trigger counter on card change
  useEffect(() => {
    resetIdle();
    idleTriggersRef.current = 0;
  }, [currentCardIndex, resetIdle]);

  // Idle timer — check if student needs help (max 2 nudges per card)
  useEffect(() => {
    // Clear any previous interval before starting a new one
    if (idleTimerRef.current) clearInterval(idleTimerRef.current);

    const checkIdle = () => {
      if (!cards[currentCardIndex]) return;
      if (idleTriggersRef.current >= MAX_IDLE_TRIGGERS_PER_CARD) return;
      if (Date.now() - lastInteractionRef.current >= IDLE_TIMEOUT_MS) {
        idleTriggersRef.current += 1;
        trackEvent("assist_idle_triggered", {
          card_index: currentCardIndex,
          trigger_count: idleTriggersRef.current,
          concept_id: session?.concept_id,
          concept_title: conceptTitle,
        });
        sendAssistMessage(null, "idle");
        lastInteractionRef.current = Date.now();
      }
    };

    idleTimerRef.current = setInterval(checkIdle, 10000);
    return () => {
      if (idleTimerRef.current) clearInterval(idleTimerRef.current);
    };
  }, [currentCardIndex, cards, sendAssistMessage]);

  const handleSubmit = (e) => {
    e.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || assistLoading) return;
    resetIdle();
    trackEvent("assist_asked", { card_index: currentCardIndex, trigger: "user", concept_id: session?.concept_id, concept_title: conceptTitle });
    sendAssistMessage(trimmed, "user");
    setInput("");
  };

  return (
    <div
      style={{
        background: "var(--color-surface)",
        borderRadius: "1rem",
        border: "2px solid var(--color-border)",
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
        height: "calc(100vh - 86px)",
        maxHeight: "700px",
      }}
    >
      {/* Header — color changes with adaptive mode */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "0.625rem",
          padding: "0.75rem 1rem",
          transition: "background 400ms ease-in-out",
          background: modeColors[mode] || modeColors.NORMAL,
        }}
      >
        <div
          style={{
            width: "2rem",
            height: "2rem",
            borderRadius: "50%",
            background: "rgba(255,255,255,0.2)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <Brain size={16} color="#fff" />
        </div>
        <div>
          <div
            style={{
              color: "#fff",
              fontWeight: 700,
              fontSize: "0.9rem",
            }}
          >
            {t("assist.title")}
          </div>
          <div
            style={{
              color: "rgba(255,255,255,0.75)",
              fontSize: "0.7rem",
              fontWeight: 500,
            }}
          >
            {t("assist.subtitle")}
          </div>
        </div>
      </div>

      {/* Messages */}
      <div
        style={{
          flex: 1,
          overflowY: "auto",
          padding: "0.75rem",
          background: "var(--color-bg)",
        }}
      >
        {/* Welcome message */}
        {assistMessages.length === 0 && (
          <div
            style={{
              textAlign: "center",
              padding: "1.5rem 0.5rem",
              color: "var(--color-text-muted)",
              fontSize: "0.85rem",
            }}
          >
            <Sparkles
              size={24}
              style={{ marginBottom: "0.375rem", opacity: 0.5 }}
            />
            <p style={{ margin: 0, fontWeight: 600 }}>
              {t("assist.welcome")}
            </p>
            <p style={{ marginTop: "0.25rem", marginBottom: 0, fontSize: "0.8rem", opacity: 0.8 }}>
              {t("assist.welcomeHint")}
            </p>
          </div>
        )}

        <AnimatePresence initial={false}>
          {assistMessages.filter(m => !m.isSystemPrompt).map((msg, idx) => (
            <motion.div
              key={idx}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
              style={{
                display: "flex",
                marginBottom: "0.5rem",
                justifyContent: msg.role === "user" ? "flex-end" : "flex-start",
              }}
            >
              <div
                style={{
                  maxWidth: "90%",
                  padding: "0.5rem 0.75rem",
                  fontSize: "0.85rem",
                  lineHeight: 1.6,
                  ...(msg.role === "user"
                    ? {
                        borderRadius: "12px 4px 12px 12px",
                        background: "var(--color-primary)",
                        color: "#fff",
                        border: "none",
                      }
                    : {
                        borderRadius: "4px 12px 12px 12px",
                        background: "var(--color-surface)",
                        color: "var(--color-text)",
                        border: "1px solid var(--color-border)",
                      }),
                }}
              >
                {msg.role === "assistant" ? (
                  <div className="markdown-content" style={{ fontSize: "0.85rem" }}>
                    <ReactMarkdown
                      remarkPlugins={[remarkMath]}
                      rehypePlugins={[rehypeKatex]}
                      skipHtml={true}
                    >
                      {msg.content}
                    </ReactMarkdown>
                  </div>
                ) : (
                  <span>{msg.content}</span>
                )}
              </div>
            </motion.div>
          ))}
        </AnimatePresence>

        {assistLoading && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            style={{
              display: "flex",
              gap: "0.25rem",
              padding: "0.375rem 0.5rem",
              alignItems: "center",
            }}
          >
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                style={{
                  width: "0.375rem",
                  height: "0.375rem",
                  borderRadius: "50%",
                  background: "var(--color-text-muted)",
                  animation: `dots-bounce 1.2s ease-in-out ${i * 0.2}s infinite`,
                }}
              />
            ))}
          </motion.div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div
        style={{
          padding: "0.625rem 0.75rem",
          borderTop: "2px solid var(--color-border)",
          background: "var(--color-surface)",
        }}
      >
        <form
          onSubmit={handleSubmit}
          style={{ display: "flex", gap: "0.375rem" }}
        >
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={t("assist.placeholder")}
            disabled={assistLoading}
            maxLength={500}
            className="ada-input"
            style={{
              flex: 1,
              padding: "0.5rem 0.75rem",
              fontSize: "0.85rem",
              borderRadius: "10px",
            }}
          />
          <button
            type="submit"
            disabled={!input.trim() || assistLoading}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              width: "38px",
              height: "38px",
              borderRadius: "10px",
              border: "none",
              flexShrink: 0,
              cursor: input.trim() && !assistLoading ? "pointer" : "not-allowed",
              background: input.trim() && !assistLoading
                ? "var(--color-primary)"
                : "var(--color-border)",
              color: input.trim() && !assistLoading
                ? "#fff"
                : "var(--color-text-muted)",
            }}
          >
            <Send size={16} />
          </button>
        </form>
      </div>
    </div>
  );
}
