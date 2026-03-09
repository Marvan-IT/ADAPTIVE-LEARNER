import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { API_BASE_URL } from "../../utils/constants";

/**
 * ConceptImage
 *
 * Renders a concept image with its GPT-4o Vision description as a separate
 * content block below the image — styled the same as concept card content.
 *
 * Props:
 *   img       {object}  Image object from the API (url, description, caption,
 *                        image_type, width, height, filename)
 *   maxWidth  {string}  CSS max-width for the image (default: "600px")
 *   className {string}  Optional extra class name on the outer wrapper
 */
export default function ConceptImage({ img, maxWidth = "600px", className = "" }) {
  const [status, setStatus] = useState("loading"); // "loading" | "loaded" | "error"

  // Prefer enriched description; fall back to legacy caption
  const description = img.description || img.caption || null;

  if (!img.url) return null;
  if (status === "error") return null;

  const src = `${API_BASE_URL}${img.url}`;

  return (
    <div className={className} style={{ marginBottom: "1.75rem" }}>
      {/* Image card */}
      <figure
        style={{
          margin: 0,
          borderRadius: "10px",
          border: "1.5px solid var(--color-border)",
          overflow: "hidden",
          backgroundColor: "#fff",
          maxWidth,
        }}
      >
        {/* Skeleton shown while loading */}
        {status === "loading" && (
          <div
            aria-hidden="true"
            style={{
              width: "100%",
              aspectRatio: img.width && img.height ? `${img.width} / ${img.height}` : "16 / 9",
              backgroundColor: "var(--color-border)",
              animation: "ada-skeleton-pulse 1.4s ease-in-out infinite",
            }}
          />
        )}

        <img
          src={src}
          alt={description || "Diagram"}
          onLoad={() => setStatus("loaded")}
          onError={() => setStatus("error")}
          style={{
            width: "100%",
            height: "auto",
            display: status === "loaded" ? "block" : "none",
          }}
        />
      </figure>

      {/* Description as a separate content block — same styling as concept card content */}
      {status === "loaded" && description && (
        <div className="markdown-content" style={{ marginTop: "0.65rem", paddingLeft: "0.25rem" }}>
          <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]} skipHtml={true}>
            {description}
          </ReactMarkdown>
        </div>
      )}

      <style>{`
        @keyframes ada-skeleton-pulse {
          0%, 100% { opacity: 1; }
          50%       { opacity: 0.45; }
        }
      `}</style>
    </div>
  );
}
