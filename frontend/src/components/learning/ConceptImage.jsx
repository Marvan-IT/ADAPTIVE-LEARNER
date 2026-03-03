import { useState } from "react";
import { API_BASE_URL } from "../../utils/constants";

/**
 * ConceptImage
 *
 * Renders a single concept image enriched with a GPT-4o Vision description and
 * relevance explanation. Falls back to the legacy `caption` field when the
 * enriched fields are absent so the component is safe to use everywhere.
 *
 * Props:
 *   img       {object}  Image object from the API (url, description, relevance,
 *                        caption, image_type, width, height, filename)
 *   maxWidth  {string}  CSS max-width for the figure (default: "600px")
 *   className {string}  Optional extra class name on the <figure>
 */
export default function ConceptImage({ img, maxWidth = "600px", className = "" }) {
  const [status, setStatus] = useState("loading"); // "loading" | "loaded" | "error"

  // Prefer enriched description; fall back to legacy caption
  const description = img.description || img.caption || null;

  // Skip images that have no description at all (guard at render site already
  // handles this, but be defensive)
  if (!description && !img.url) return null;

  const src = img.url ? `${API_BASE_URL}${img.url}` : null;

  // If the image fails to load, hide the entire figure gracefully
  if (status === "error") return null;

  return (
    <figure
      className={className}
      style={{
        margin: "0 0 1rem 0",
        borderRadius: "10px",
        border: "1.5px solid var(--color-border)",
        overflow: "hidden",
        backgroundColor: "#fff",
        maxWidth,
      }}
    >
      {/* Skeleton shown while the image is still loading */}
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

      {/* Only render the caption block once loaded and when we have something to show */}
      {status === "loaded" && description && (
        <figcaption
          style={{
            padding: "0.55rem 0.85rem",
            borderTop: "1px solid var(--color-border)",
            backgroundColor: "var(--color-bg)",
          }}
        >
          <p
            style={{
              fontSize: "0.875rem",
              color: "var(--color-text-muted)",
              lineHeight: 1.6,
              marginTop: "0.5rem",
              fontStyle: "italic",
            }}
          >
            {description}
          </p>
        </figcaption>
      )}

      <style>{`
        @keyframes ada-skeleton-pulse {
          0%, 100% { opacity: 1; }
          50%       { opacity: 0.45; }
        }
      `}</style>
    </figure>
  );
}
