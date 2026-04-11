import { useState, useEffect, useCallback } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { getBookSections, getBookChunks, getBookGraph, publishBook, dropBook, getAdminBooks } from "../api/admin";
import { resolveImageUrl } from "../api/client";

// Badge helpers

function sectionBadges(title) {
  const badges = [];
  if (/\(optional\)/i.test(title)) {
    badges.push({ label: "Optional", color: "#9ca3af", bg: "#f3f4f6" });
  }
  if (/\b(lab|experiment)\b/i.test(title)) {
    badges.push({ label: "Lab", color: "#1d4ed8", bg: "#dbeafe" });
  }
  return badges;
}

const CHUNK_TYPE_STYLES = {
  teaching:           { label: "teaching",           color: "#166534", bg: "#dcfce7" },
  lab:                { label: "lab",                color: "#1d4ed8", bg: "#dbeafe" },
  exercise:           { label: "exercise",           color: "#92400e", bg: "#fef3c7" },
  learning_objective: { label: "learning objective", color: "#581c87", bg: "#f3e8ff" },
};

function ChunkTypeBadge({ type }) {
  const style = CHUNK_TYPE_STYLES[type] || { label: type || "unknown", color: "#374151", bg: "#f3f4f6" };
  return (
    <span style={{
      display: "inline-block",
      fontSize: 11,
      fontWeight: 600,
      letterSpacing: "0.03em",
      padding: "2px 7px",
      borderRadius: 4,
      color: style.color,
      background: style.bg,
      textTransform: "uppercase",
    }}>
      {style.label}
    </span>
  );
}

function SectionBadge({ label, color, bg }) {
  return (
    <span style={{
      display: "inline-block",
      fontSize: 10,
      fontWeight: 600,
      padding: "1px 5px",
      borderRadius: 3,
      color,
      background: bg,
      marginLeft: 5,
      verticalAlign: "middle",
    }}>
      {label}
    </span>
  );
}

export default function AdminReviewPage() {
  const { slug } = useParams();
  const navigate = useNavigate();
  const [sections, setSections] = useState([]);
  const [selectedConcept, setSelectedConcept] = useState(null);
  const [chunks, setChunks] = useState([]);
  const [graphInfo, setGraphInfo] = useState(null);
  const [bookSubject, setBookSubject] = useState(null);
  const [loading, setLoading] = useState(true);
  const [chunksLoading, setChunksLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);

  useEffect(() => {
    Promise.all([
      getBookSections(slug),
      getBookGraph(slug).catch(() => ({ data: null })),
      getAdminBooks().catch(() => ({ data: [] })),
    ]).then(([secRes, graphRes, booksRes]) => {
      setSections(secRes.data);
      if (graphRes.data) {
        setGraphInfo({ nodes: graphRes.data.nodes?.length || 0, edges: graphRes.data.edges?.length || 0 });
      }
      const book = booksRes.data.find((b) => b.slug === slug);
      if (book) setBookSubject(book.subject);
      setLoading(false);
    }).catch((e) => { console.error(e); setLoading(false); });
  }, [slug]);

  const loadChunks = (conceptId) => {
    setSelectedConcept(conceptId);
    setChunks([]);
    setChunksLoading(true);
    getBookChunks(slug, conceptId)
      .then((r) => setChunks(r.data))
      .catch(console.error)
      .finally(() => setChunksLoading(false));
  };

  const scrollToChunk = useCallback((chunkId) => {
    const el = document.getElementById(`chunk-${chunkId}`);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  const handleDrop = () => {
    if (!window.confirm("Drop this book? This permanently deletes all extracted data.")) return;
    setActionLoading(true);
    dropBook(slug)
      .then(() => navigate(bookSubject ? `/admin/subjects/${bookSubject}` : "/admin"))
      .catch((e) => { alert(e.response?.data?.detail || "Failed"); setActionLoading(false); });
  };

  const handleProceed = () => {
    if (!window.confirm("Publish this book? Students will be able to access it.")) return;
    setActionLoading(true);
    publishBook(slug)
      .then(() => navigate(bookSubject ? `/admin/subjects/${bookSubject}` : "/admin"))
      .catch((e) => { alert(e.response?.data?.detail || "Failed to publish"); setActionLoading(false); });
  };

  if (loading) return <div style={{ padding: 40 }}>Loading...</div>;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", fontFamily: "sans-serif" }}>
      {/* Header */}
      <div style={{ padding: "16px 24px", borderBottom: "1px solid #e5e7eb", display: "flex", alignItems: "center", gap: 16, flexShrink: 0 }}>
        <button onClick={() => navigate(-1)} style={{ background: "none", border: "none", color: "#3b82f6", cursor: "pointer", fontSize: 14 }}>← Back</button>
        <h2 style={{ margin: 0, fontSize: 18 }}>{slug.replace(/_/g, " ")} — Review</h2>
      </div>

      {/* Three panels */}
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>

        {/* Left: section tree */}
        <div style={{ width: 280, borderRight: "1px solid #e5e7eb", overflowY: "auto", padding: 16, flexShrink: 0 }}>
          {sections.length === 0 ? (
            <div style={{ fontSize: 13, color: "#9ca3af" }}>No sections found</div>
          ) : (
            sections.map((chapter) => (
              <div key={chapter.chapter} style={{ marginBottom: 16 }}>
                <div style={{ fontWeight: 600, fontSize: 12, color: "#6b7280", marginBottom: 8, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                  Chapter {chapter.chapter}
                </div>
                {chapter.sections.map((sec) => {
                  const title = (sec.section || sec.heading || "").replace(/ \| /g, " ");
                  const badges = sectionBadges(title);
                  const isSelected = selectedConcept === sec.concept_id;
                  return (
                    <div key={sec.concept_id}>
                      {/* Section row */}
                      <div
                        onClick={() => loadChunks(sec.concept_id)}
                        style={{
                          padding: "6px 8px",
                          borderRadius: 6,
                          cursor: "pointer",
                          fontSize: 13,
                          marginBottom: 2,
                          background: isSelected ? "#eff6ff" : "transparent",
                          color: isSelected ? "#2563eb" : "#374151",
                          display: "flex",
                          alignItems: "flex-start",
                          gap: 4,
                          flexWrap: "wrap",
                        }}>
                        <span style={{ flex: "1 1 auto" }}>
                          {title}
                          {badges.map((b) => (
                            <SectionBadge key={b.label} {...b} />
                          ))}
                        </span>
                        <span style={{ fontSize: 11, color: "#9ca3af", flexShrink: 0, paddingTop: 1 }}>
                          {sec.chunk_count}c{sec.image_count > 0 ? ` ${sec.image_count}img` : ""}
                        </span>
                      </div>

                      {/* Sub-items: chunk headings when this section is selected */}
                      {isSelected && !chunksLoading && chunks.length > 0 && (
                        <div style={{ marginBottom: 4 }}>
                          {chunks.map((chunk) => (
                            <div
                              key={chunk.id}
                              onClick={() => scrollToChunk(chunk.id)}
                              style={{
                                padding: "4px 8px 4px 20px",
                                fontSize: 12,
                                color: "#4b5563",
                                cursor: "pointer",
                                borderRadius: 4,
                                lineHeight: 1.4,
                                borderLeft: "2px solid #bfdbfe",
                                marginBottom: 1,
                                marginLeft: 8,
                              }}
                              onMouseEnter={(e) => { e.currentTarget.style.background = "#f0f9ff"; e.currentTarget.style.color = "#1d4ed8"; }}
                              onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "#4b5563"; }}
                            >
                              {chunk.heading || `Chunk ${chunks.indexOf(chunk) + 1}`}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            ))
          )}
        </div>

        {/* Center: chunks */}
        <div style={{ flex: 1, overflowY: "auto", padding: 24 }}>
          {!selectedConcept ? (
            <div style={{ color: "#9ca3af", textAlign: "center", paddingTop: 60, fontSize: 14 }}>
              Select a section from the left panel
            </div>
          ) : chunksLoading ? (
            <div style={{ color: "#9ca3af", fontSize: 14 }}>Loading chunks...</div>
          ) : chunks.length === 0 ? (
            <div style={{ color: "#9ca3af", fontSize: 14 }}>No chunks found for this section</div>
          ) : (
            chunks.map((chunk, i) => (
              <div
                key={chunk.id}
                id={`chunk-${chunk.id}`}
                style={{
                  marginBottom: 20,
                  padding: "18px 20px",
                  borderRadius: 8,
                  border: "1px solid #e5e7eb",
                  background: "#fff",
                  boxShadow: "0 1px 3px rgba(0,0,0,0.04)",
                  scrollMarginTop: 16,
                }}
              >
                {/* Chunk header: heading + badges */}
                <div style={{ display: "flex", alignItems: "flex-start", gap: 10, marginBottom: 10, flexWrap: "wrap" }}>
                  <h4 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: "#111827", flex: "1 1 auto", lineHeight: 1.4 }}>
                    {chunk.heading || `Chunk ${i + 1}`}
                  </h4>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
                    {chunk.chunk_type && <ChunkTypeBadge type={chunk.chunk_type} />}
                    {chunk.is_optional && (
                      <span style={{ fontSize: 11, color: "#6b7280", fontStyle: "italic" }}>(Optional)</span>
                    )}
                  </div>
                </div>

                {/* Chunk text */}
                <p style={{ margin: "0 0 0", fontSize: 14, lineHeight: 1.7, color: "#374151", whiteSpace: "pre-wrap" }}>
                  {chunk.text}
                </p>

                {/* Images */}
                {chunk.images?.length > 0 && (
                  <div style={{ marginTop: 14, display: "flex", flexWrap: "wrap", gap: 12 }}>
                    {chunk.images.map((img, j) => (
                      <div key={j} style={{ maxWidth: 360 }}>
                        <img
                          src={resolveImageUrl(img.image_url)}
                          alt={img.caption || "Image"}
                          style={{ maxWidth: "100%", maxHeight: 280, borderRadius: 6, objectFit: "contain", border: "1px solid #f3f4f6" }}
                        />
                        {img.caption && (
                          <p style={{ fontSize: 12, color: "#6b7280", margin: "4px 0 0", lineHeight: 1.4 }}>{img.caption}</p>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))
          )}
        </div>

        {/* Right: graph info */}
        <div style={{ width: 200, borderLeft: "1px solid #e5e7eb", padding: 16, flexShrink: 0 }}>
          <div style={{ fontWeight: 600, fontSize: 12, color: "#6b7280", marginBottom: 12, textTransform: "uppercase", letterSpacing: "0.05em" }}>Dependency Graph</div>
          {graphInfo ? (
            <div>
              <div style={{ fontSize: 13, marginBottom: 8 }}>
                <span style={{ fontWeight: 500 }}>{graphInfo.nodes}</span> concepts
              </div>
              <div style={{ fontSize: 13 }}>
                <span style={{ fontWeight: 500 }}>{graphInfo.edges}</span> prerequisites
              </div>
            </div>
          ) : (
            <div style={{ fontSize: 13, color: "#9ca3af" }}>Graph not available</div>
          )}
        </div>
      </div>

      {/* Bottom action bar */}
      <div style={{ padding: "16px 24px", borderTop: "1px solid #e5e7eb", display: "flex", justifyContent: "space-between", background: "#fff", flexShrink: 0 }}>
        <button onClick={handleDrop} disabled={actionLoading}
          style={{ padding: "10px 20px", background: "#ef4444", color: "#fff", border: "none", borderRadius: 8, cursor: "pointer", fontSize: 14, opacity: actionLoading ? 0.6 : 1 }}>
          Drop (Wipe Everything)
        </button>
        <button onClick={handleProceed} disabled={actionLoading}
          style={{ padding: "10px 20px", background: "#10b981", color: "#fff", border: "none", borderRadius: 8, cursor: "pointer", fontSize: 14, opacity: actionLoading ? 0.6 : 1 }}>
          Proceed — Publish
        </button>
      </div>
    </div>
  );
}
