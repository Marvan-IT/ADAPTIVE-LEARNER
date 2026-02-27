import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { useSession } from "../../context/SessionContext";
import { useTheme } from "../../context/ThemeContext";
import { themes } from "../../theme/themes";
import ConceptImage from "./ConceptImage";
import { MessageCircle, BookOpen, Sparkles } from "lucide-react";

export default function PresentationView() {
  const { presentation, conceptTitle, startCheck, loading, images } = useSession();
  const { style } = useTheme();
  const theme = themes[style] || themes.default;

  // Only show DIAGRAM-type images with reasonable size (skip tiny formula renders)
  // Also require at least a description or legacy caption so we never show a
  // bare image with no context.
  const usefulDiagrams = (images || []).filter(
    (img) =>
      (img.image_type || "").toUpperCase() === "DIAGRAM" &&
      (img.width || 0) >= 200 &&
      (img.height || 0) >= 80 &&
      (img.description || img.caption)
  );

  return (
    <div>
      {/* ─── Lesson Card ─── */}
      <div style={{
        backgroundColor: "var(--color-surface)",
        borderRadius: "16px",
        border: "2px solid var(--color-border)",
        overflow: "hidden",
        marginBottom: "1.5rem",
      }}>
        {/* Top banner */}
        <div style={{
          background: `linear-gradient(135deg, var(--color-primary), var(--color-accent))`,
          padding: "1.5rem 2rem",
          color: "#fff",
        }}>
          <div style={{
            display: "flex", alignItems: "center", gap: "0.5rem",
            fontSize: "0.85rem", fontWeight: 600, opacity: 0.9,
            marginBottom: "0.4rem",
          }}>
            <BookOpen size={16} />
            LESSON
          </div>
          <h1 style={{
            fontSize: "1.7rem", fontWeight: 800, margin: 0,
            color: "#fff",
          }}>
            {conceptTitle}
          </h1>
          <p style={{ fontSize: "0.9rem", opacity: 0.85, marginTop: "0.3rem" }}>
            {theme.greeting}
          </p>
        </div>

        {/* AI-generated lesson content */}
        <div
          className="markdown-content"
          style={{ padding: "1.75rem 2rem" }}
        >
          <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>
            {presentation}
          </ReactMarkdown>

          {/* Useful textbook diagrams embedded within the lesson */}
          {usefulDiagrams.length > 0 && (
            <div style={{ marginTop: "1.5rem" }}>
              {usefulDiagrams.slice(0, 5).map((img, i) => (
                <ConceptImage key={i} img={img} maxWidth="600px" />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ─── Ready for Quiz Button ─── */}
      <div style={{
        backgroundColor: "var(--color-surface)",
        borderRadius: "14px",
        border: "2px solid var(--color-primary)",
        padding: "1.25rem",
        textAlign: "center",
      }}>
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "center", gap: "0.4rem",
          color: "var(--color-text-muted)", fontSize: "0.9rem", marginBottom: "0.75rem",
        }}>
          <Sparkles size={16} />
          Finished reading? Let's test your understanding!
        </div>
        <button
          onClick={startCheck}
          disabled={loading}
          style={{
            display: "inline-flex", alignItems: "center", gap: "0.5rem",
            padding: "0.85rem 2.5rem", borderRadius: "12px", border: "none",
            backgroundColor: "var(--color-primary)", color: "#fff",
            fontSize: "1.1rem", fontWeight: 700,
            cursor: loading ? "wait" : "pointer",
            fontFamily: "inherit",
            opacity: loading ? 0.7 : 1,
            transition: "all 0.2s",
            boxShadow: "0 4px 12px rgba(59, 130, 246, 0.3)",
          }}
        >
          <MessageCircle size={20} />
          {loading ? "Getting ready..." : "Start Quiz"}
        </button>
      </div>
    </div>
  );
}
