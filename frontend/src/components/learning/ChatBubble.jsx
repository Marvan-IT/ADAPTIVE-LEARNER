import { useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { Brain, User } from "lucide-react";

export default function ChatBubble({ role, content }) {
  const { t } = useTranslation();
  const isAda = role === "assistant";

  return (
    <div style={{
      display: "flex",
      flexDirection: isAda ? "row" : "row-reverse",
      gap: "0.6rem",
      marginBottom: "1.1rem",
    }}>
      {/* Avatar */}
      <div style={{
        width: "34px", height: "34px", borderRadius: "50%", flexShrink: 0,
        display: "flex", alignItems: "center", justifyContent: "center",
        backgroundColor: isAda ? "var(--color-primary)" : "var(--color-accent)",
        color: "#fff",
        boxShadow: "0 2px 6px rgba(0,0,0,0.1)",
      }}>
        {isAda ? <Brain size={16} /> : <User size={16} />}
      </div>

      {/* Bubble */}
      <div style={{ maxWidth: "78%", display: "flex", flexDirection: "column", gap: "0.15rem" }}>
        <div style={{
          fontSize: "0.7rem", fontWeight: 700, color: "var(--color-text-muted)",
          paddingLeft: isAda ? "0.3rem" : "0",
          paddingRight: isAda ? "0" : "0.3rem",
          textAlign: isAda ? "left" : "right",
        }}>
          {isAda ? t("chat.ada") : t("chat.you")}
        </div>
        <div
          className={isAda ? "markdown-content" : ""}
          style={{
            padding: "0.75rem 1rem",
            borderRadius: isAda ? "4px 14px 14px 14px" : "14px 4px 14px 14px",
            backgroundColor: isAda ? "var(--color-surface)" : "var(--color-primary)",
            color: isAda ? "var(--color-text)" : "#fff",
            border: isAda ? "1px solid var(--color-border)" : "none",
            fontSize: "0.95rem",
            lineHeight: 1.6,
            boxShadow: "0 1px 4px rgba(0,0,0,0.05)",
          }}
        >
          {isAda ? (
            <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]} skipHtml={true}>
              {content}
            </ReactMarkdown>
          ) : (
            <p style={{ margin: 0 }}>{content}</p>
          )}
        </div>
      </div>
    </div>
  );
}
