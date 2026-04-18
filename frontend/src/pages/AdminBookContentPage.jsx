import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useToast } from "../components/ui/Toast";
import { useDialog } from "../context/DialogProvider";
import {
  getBookSections, getBookChunks, getBookGraph,
  updateChunk as updateChunkApi,
  toggleChunkVisibility as toggleChunkVisibilityApi,
  toggleChunkExamGate as toggleChunkExamGateApi,
  mergeChunks as mergeChunksApi,
  splitChunk as splitChunkApi,
  renameSection, toggleSectionOptional, toggleSectionExamGate, toggleSectionVisibility,
  getGraphEdges, modifyGraphEdge,
  regenerateChunkEmbedding, regenerateConceptEmbeddings,
  promoteToSection,
} from "../api/admin";
import { resolveImageUrl } from "../api/client";
import useDraftMode from "../hooks/useDraftMode";

// ── Badge helpers ──────────────────────────────────────────────────────────

function sectionBadges(title) {
  const badges = [];
  if (/\(optional\)/i.test(title)) {
    badges.push({ label: "Optional", cls: "bg-gray-100 text-gray-500" });
  }
  if (/\b(lab|experiment)\b/i.test(title)) {
    badges.push({ label: "Lab", cls: "bg-blue-100 text-blue-700" });
  }
  return badges;
}

const CHUNK_TYPE_STYLES = {
  teaching:           { label: "teaching",           bg: "#DCFCE7", color: "#15803D" },
  lab:                { label: "lab",                bg: "#DBEAFE", color: "#1D4ED8" },
  exercise:           { label: "exercise",           bg: "#FEF3C7", color: "#B45309" },
  learning_objective: { label: "learning objective", bg: "#F3E8FF", color: "#7E22CE" },
};

function ChunkTypeBadge({ type }) {
  const cfg = CHUNK_TYPE_STYLES[type] || { label: type || "unknown", bg: "#F1F5F9", color: "#475569" };
  return (
    <span style={{ display: "inline-block", fontSize: "11px", fontWeight: 600, letterSpacing: "0.05em", padding: "2px 8px", borderRadius: "4px", textTransform: "uppercase", backgroundColor: cfg.bg, color: cfg.color }}>
      {cfg.label}
    </span>
  );
}

const SECTION_BADGE_STYLES = {
  "bg-gray-100 text-gray-500": { bg: "#F1F5F9", color: "#64748B" },
  "bg-blue-100 text-blue-700": { bg: "#DBEAFE", color: "#1D4ED8" },
};

function SectionBadge({ label, cls }) {
  const s = SECTION_BADGE_STYLES[cls] || { bg: "#F1F5F9", color: "#64748B" };
  return (
    <span style={{ display: "inline-block", fontSize: "10px", fontWeight: 600, padding: "2px 6px", borderRadius: "4px", verticalAlign: "middle", marginLeft: "6px", backgroundColor: s.bg, color: s.color }}>
      {label}
    </span>
  );
}

// ── Accordion prerequisite editor ─────────────────────────────────────────────

function PrereqAccordion({ slug, graphEdges, sections, allConcepts, graphInfo, onEdgesChanged }) {
  const { toast } = useToast();
  const dialog = useDialog();
  const [expandedId, setExpandedId] = useState(null);
  const [addingFor, setAddingFor] = useState(null);
  const [newPrereq, setNewPrereq] = useState("");
  const [busy, setBusy] = useState(false);

  const flatSections = useMemo(() => {
    const list = [];
    (sections || []).forEach((ch) =>
      (ch.sections || []).forEach((s) => {
        list.push({ id: s.concept_id, section: s.section, label: s.heading || s.concept_id });
      })
    );
    return list;
  }, [sections]);

  const nameMap = useMemo(() => {
    const m = {};
    flatSections.forEach((s) => { m[s.id] = `${s.section} | ${s.label}`; });
    (allConcepts || []).forEach((c) => {
      if (c.concept_id && c.label && !m[c.concept_id]) m[c.concept_id] = c.label;
    });
    return m;
  }, [flatSections, allConcepts]);

  const getName = (id) => nameMap[id] || id;
  const getPrereqs = (conceptId) => (graphEdges || []).filter((e) => e.target === conceptId).map((e) => e.source);
  const allIds = useMemo(() => flatSections.map((s) => s.id), [flatSections]);

  const handleAdd = async (targetId) => {
    if (!newPrereq || !targetId) return;
    setBusy(true);
    try {
      await modifyGraphEdge(slug, "add_edge", newPrereq, targetId);
      setNewPrereq("");
      setAddingFor(null);
      if (onEdgesChanged) onEdgesChanged();
    } catch (e) {
      toast({ variant: "danger", title: "Error", description: e.response?.data?.detail || "Failed to add prerequisite" });
    } finally { setBusy(false); }
  };

  const handleRemove = async (sourceId, targetId) => {
    if (!(await dialog.confirm({ title: "Remove Prerequisite", message: `Remove "${getName(sourceId)}" as prerequisite?`, variant: "danger", confirmLabel: "Confirm" }))) return;
    setBusy(true);
    try {
      await modifyGraphEdge(slug, "remove_edge", sourceId, targetId);
      if (onEdgesChanged) onEdgesChanged();
    } catch (e) {
      toast({ variant: "danger", title: "Error", description: e.response?.data?.detail || "Failed" });
    } finally { setBusy(false); }
  };

  return (
    <div>
      <div style={{ fontSize: "11px", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", color: "#94A3B8", marginBottom: "12px" }}>Prerequisites</div>
      {graphInfo && (
        <div style={{ display: "flex", gap: "12px", marginBottom: "16px", fontSize: "12px", color: "#64748B" }}>
          <span><strong style={{ color: "#0F172A" }}>{graphInfo.nodes}</strong> sections</span>
          <span><strong style={{ color: "#0F172A" }}>{graphInfo.edges}</strong> edges</span>
        </div>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
        {flatSections.map((sec) => {
          const prereqs = getPrereqs(sec.id);
          const isExpanded = expandedId === sec.id;
          const available = allIds.filter((c) => c !== sec.id && !prereqs.includes(c));
          return (
            <div key={sec.id}>
              <div
                onClick={() => setExpandedId(isExpanded ? null : sec.id)}
                style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "8px 10px", borderRadius: "6px", cursor: "pointer", backgroundColor: isExpanded ? "#FFF7ED" : "transparent", border: isExpanded ? "1px solid #FED7AA" : "1px solid transparent" }}
              >
                <span style={{ fontSize: "12px", color: isExpanded ? "#EA580C" : "#0F172A", fontWeight: isExpanded ? 600 : 400 }}>
                  {isExpanded ? "▼" : "▶"} <strong>{sec.section}</strong> {sec.label}
                </span>
                <span style={{ fontSize: "11px", color: prereqs.length > 0 ? "#EA580C" : "#94A3B8", fontWeight: 500 }}>{prereqs.length}</span>
              </div>
              {isExpanded && (
                <div style={{ paddingLeft: "20px", paddingTop: "6px", paddingBottom: "10px" }}>
                  {prereqs.length === 0 ? (
                    <div style={{ fontSize: "12px", color: "#94A3B8", marginBottom: "8px" }}>No prerequisites</div>
                  ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: "4px", marginBottom: "8px" }}>
                      {prereqs.map((srcId) => (
                        <div key={srcId} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "4px 8px", borderRadius: "6px", backgroundColor: "#F1F5F9", fontSize: "12px" }}>
                          <span style={{ color: "#334155" }}>{getName(srcId)}</span>
                          <button onClick={() => handleRemove(srcId, sec.id)} disabled={busy} style={{ background: "none", border: "none", color: "#EF4444", cursor: "pointer", fontSize: "11px", fontWeight: 600 }}>✕</button>
                        </div>
                      ))}
                    </div>
                  )}
                  {addingFor === sec.id ? (
                    <div style={{ display: "flex", gap: "4px" }}>
                      <select value={newPrereq} onChange={(e) => setNewPrereq(e.target.value)} style={{ flex: 1, fontSize: "11px", padding: "4px 6px", border: "1px solid #E2E8F0", borderRadius: "6px" }} disabled={busy}>
                        <option value="">Select...</option>
                        {available.map((c) => <option key={c} value={c}>{getName(c)}</option>)}
                      </select>
                      <button onClick={() => handleAdd(sec.id)} disabled={busy || !newPrereq} style={{ padding: "4px 8px", borderRadius: "6px", backgroundColor: !newPrereq || busy ? "#CBD5E1" : "#22C55E", color: "#FFF", border: "none", cursor: !newPrereq || busy ? "not-allowed" : "pointer", fontSize: "11px", fontWeight: 600 }}>Add</button>
                      <button onClick={() => { setAddingFor(null); setNewPrereq(""); }} style={{ padding: "4px 6px", borderRadius: "6px", backgroundColor: "#F1F5F9", border: "none", cursor: "pointer", fontSize: "11px", color: "#64748B" }}>✕</button>
                    </div>
                  ) : (
                    <button onClick={() => setAddingFor(sec.id)} style={{ fontSize: "11px", color: "#EA580C", background: "none", border: "none", cursor: "pointer", fontWeight: 500, padding: 0 }}>+ Add prerequisite</button>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────

export default function AdminBookContentPage() {
  const { slug } = useParams();
  useTranslation();
  const { toast } = useToast();
  const dialog = useDialog();

  // Core data
  const [sections, setSections] = useState([]);
  const [selectedConcept, setSelectedConcept] = useState(null);
  const [serverChunks, setServerChunks] = useState([]);
  const [graphInfo, setGraphInfo] = useState(null);
  const [allConcepts, setAllConcepts] = useState([]);
  const [graphEdges, setGraphEdges] = useState([]);
  const [splittingChunk, setSplittingChunk] = useState(null);
  const [bookTitle, setBookTitle] = useState(null);

  // Loading flags
  const [loading, setLoading] = useState(true);
  const [chunksLoading, setChunksLoading] = useState(false);
  const [regenAllBusy, setRegenAllBusy] = useState(false);

  // Inline chunk editing
  const [editingChunk, setEditingChunk] = useState(null);
  const [editHeading, setEditHeading] = useState("");
  const [editText, setEditText] = useState("");

  // Scroll-sync: track which chunk is visible in the center panel
  const [activeChunkId, setActiveChunkId] = useState(null);
  const centerRef = useRef(null);

  // Draft mode
  const {
    draftChunks,
    isDirty,
    modifiedChunkIds,
    pendingStructural,
    editChunk,
    mergeDraftChunks,
    splitDraftChunk,
    saveDraft,
    discardDraft,
    saveStatus,
  } = useDraftMode(slug, selectedConcept, serverChunks);

  // ── Initial load ───────────────────────────────────────────────────────

  useEffect(() => {
    setLoading(true);
    Promise.all([
      getBookSections(slug),
      getBookGraph(slug).catch(() => ({ data: null })),
    ]).then(([secRes, graphRes]) => {
      const secData = secRes.data;
      const chaptersArr = secData?.chapters || secData || [];
      setSections(chaptersArr);
      setBookTitle(secData?.title || null);
      const concepts = [];
      chaptersArr.forEach((ch) =>
        ch.sections.forEach((s) =>
          concepts.push({
            concept_id: s.concept_id,
            label: s.section && s.heading && s.heading !== s.section
              ? `${s.section} — ${s.heading}`
              : (s.section || s.concept_id),
          })
        )
      );
      setAllConcepts(concepts);
      if (graphRes.data) {
        setGraphInfo({ nodes: graphRes.data.nodes?.length || 0, edges: graphRes.data.edges?.length || 0 });
      }
      setLoading(false);
    }).catch((e) => { console.error(e); setLoading(false); });

    getGraphEdges(slug).then((r) => setGraphEdges(r.data || [])).catch(() => {});
  }, [slug]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Chunk loading ──────────────────────────────────────────────────────

  const loadChunks = useCallback(async (conceptId) => {
    setSelectedConcept(conceptId);
    setServerChunks([]);
    setEditingChunk(null);
    setChunksLoading(true);
    try {
      const r = await getBookChunks(slug, conceptId);
      const chunks = r.data || [];
      setServerChunks(chunks);
      return chunks;
    } catch (e) {
      console.error(e);
      return [];
    } finally {
      setChunksLoading(false);
    }
  }, [slug]);

  const scrollToChunk = useCallback((chunkId) => {
    const el = document.getElementById(`chunk-${chunkId}`);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  // Scroll-sync: observe which chunk is in view and highlight in left panel
  useEffect(() => {
    const container = centerRef.current;
    if (!container || draftChunks.length === 0) return;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            const id = entry.target.id.replace("chunk-", "");
            setActiveChunkId(id);
            const leftEl = document.getElementById(`left-chunk-${id}`);
            if (leftEl) leftEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
            break;
          }
        }
      },
      { root: container, rootMargin: "-10% 0px -60% 0px", threshold: 0 }
    );
    draftChunks.forEach((c) => {
      const el = document.getElementById(`chunk-${c.id}`);
      if (el) observer.observe(el);
    });
    return () => observer.disconnect();
  }, [draftChunks]);

  // ── Chunk handlers (draft mutations — NOT immediate API calls) ─────────

  const startEdit = (chunk) => {
    setEditingChunk(chunk.id);
    setEditHeading(chunk.heading || "");
    setEditText(chunk.text || "");
  };

  const handleSaveEdit = (chunkId) => {
    editChunk(chunkId, { heading: editHeading, text: editText });
    setEditingChunk(null);
  };

  const handleToggleVisibility = (chunkId) => {
    const chunk = draftChunks.find((c) => c.id === chunkId);
    if (chunk) editChunk(chunkId, { is_hidden: !chunk.is_hidden });
  };

  const handleToggleOptional = (chunk) => {
    editChunk(chunk.id, { is_optional: !chunk.is_optional });
  };

  const handleToggleExamGate = (chunk) => {
    editChunk(chunk.id, { exam_disabled: !chunk.exam_disabled });
  };

  const handleToggleChunkType = (chunk) => {
    const nextType = chunk.chunk_type === "exercise" ? "teaching" : "exercise";
    editChunk(chunk.id, { chunk_type: nextType });
  };

  const handleMerge = async (id1, id2) => {
    if (!(await dialog.confirm({ title: "Merge Chunks", message: "Merge these two chunks? This will be applied when you save.", variant: "primary", confirmLabel: "Merge" }))) return;
    mergeDraftChunks(id1, id2);
  };

  const handleSplit = (chunkId) => {
    setSplittingChunk(chunkId);
  };

  const handleSplitAt = (chunkId, position) => {
    splitDraftChunk(chunkId, position);
    setSplittingChunk(null);
  };

  // ── Immediate handlers (bypass draft — go straight to API) ────────────

  const handleRegenEmbedding = async (chunkId) => {
    try {
      await regenerateChunkEmbedding(chunkId);
      loadChunks(selectedConcept);
    } catch (e) {
      toast({ variant: "danger", title: "Error", description: e.response?.data?.detail || "Failed to regenerate embedding" });
    }
  };

  // ── Section handlers (always immediate) ───────────────────────────────

  const handleRenameSection = async (sec) => {
    const newName = window.prompt("New section name:", sec.display_name || sec.section || "");
    if (!newName || newName.trim() === "") return;
    try {
      await renameSection(sec.concept_id, slug, newName.trim());
      const secRes = await getBookSections(slug);
      const secData = secRes.data;
      setSections(secData?.chapters || secData || []);
      if (secData?.title) setBookTitle(secData.title);
      if (selectedConcept) loadChunks(selectedConcept);
    } catch (e) {
      toast({ variant: "danger", title: "Error", description: e.response?.data?.detail || "Failed to rename" });
    }
  };

  const handleToggleSectionOptional = async (sec) => {
    if (selectedConcept === sec.concept_id && isDirty) {
      if (!(await dialog.confirm({ title: "Unsaved Changes", message: "This section has unsaved chunk edits that will be discarded. Continue?", variant: "danger", confirmLabel: "Continue" }))) return;
    }
    try {
      await toggleSectionOptional(sec.concept_id, slug, !sec.is_optional);
      const r = await getBookSections(slug);
      setSections(r.data?.chapters || r.data || []);
      if (r.data?.title) setBookTitle(r.data.title);
      if (selectedConcept === sec.concept_id) {
        await loadChunks(sec.concept_id);
      }
    } catch (e) {
      toast({ variant: "danger", title: "Error", description: e.response?.data?.detail || e.message || "Failed to toggle optional" });
    }
  };

  const handleToggleSectionExamGate = async (sec) => {
    if (selectedConcept === sec.concept_id && isDirty) {
      if (!(await dialog.confirm({ title: "Unsaved Changes", message: "This section has unsaved chunk edits that will be discarded. Continue?", variant: "danger", confirmLabel: "Continue" }))) return;
    }
    try {
      await toggleSectionExamGate(sec.concept_id, slug, !sec.exam_disabled);
      const r = await getBookSections(slug);
      setSections(r.data?.chapters || r.data || []);
      if (r.data?.title) setBookTitle(r.data.title);
      if (selectedConcept === sec.concept_id) {
        await loadChunks(sec.concept_id);
      }
    } catch (e) {
      toast({ variant: "danger", title: "Error", description: e.response?.data?.detail || e.message || "Failed to toggle exam gate" });
    }
  };

  const handleToggleSectionVisibility = async (sec) => {
    if (selectedConcept === sec.concept_id && isDirty) {
      if (!(await dialog.confirm({ title: "Unsaved Changes", message: "This section has unsaved chunk edits that will be discarded. Continue?", variant: "danger", confirmLabel: "Continue" }))) return;
    }
    const newHidden = !sec.is_hidden;
    // Optimistic update — flip the section flag immediately so the UI reacts
    setSections((prev) =>
      prev.map((ch) => ({
        ...ch,
        sections: ch.sections.map((s) =>
          s.concept_id === sec.concept_id
            ? { ...s, is_hidden: newHidden, hidden_count: newHidden ? s.chunk_count : 0 }
            : s
        ),
      }))
    );
    try {
      await toggleSectionVisibility(sec.concept_id, slug, newHidden);
      // Reconcile with server truth
      const r = await getBookSections(slug);
      setSections(r.data?.chapters || r.data || []);
      if (r.data?.title) setBookTitle(r.data.title);
      if (selectedConcept === sec.concept_id) {
        await loadChunks(sec.concept_id);
      }
    } catch (e) {
      // Revert optimistic update on failure
      setSections((prev) =>
        prev.map((ch) => ({
          ...ch,
          sections: ch.sections.map((s) =>
            s.concept_id === sec.concept_id
              ? { ...s, is_hidden: sec.is_hidden, hidden_count: sec.hidden_count }
              : s
          ),
        }))
      );
      toast({ variant: "danger", title: "Error", description: e.response?.data?.detail || e.message || "Failed to toggle section visibility" });
    }
  };

  // ── Embedding regeneration (always immediate) ─────────────────────────

  const staleCount = draftChunks.filter((c) => !c.has_embedding).length;

  const handleRegenAllStale = async () => {
    if (!selectedConcept) return;
    if (!(await dialog.confirm({ title: "Regenerate All Embeddings", message: `Regenerate embeddings for ${staleCount} stale chunk(s) in this section?`, variant: "danger", confirmLabel: "Confirm" }))) return;
    setRegenAllBusy(true);
    try {
      await regenerateConceptEmbeddings(selectedConcept, slug);
      loadChunks(selectedConcept);
    } catch (e) {
      toast({ variant: "danger", title: "Error", description: e.response?.data?.detail || "Failed to regenerate embeddings" });
    } finally {
      setRegenAllBusy(false);
    }
  };

  // ── Draft save / discard handlers ─────────────────────────────────────

  const handleSaveAll = async () => {
    try {
      await saveDraft({
        updateChunk: (id, changes) => updateChunkApi(id, changes),
        mergeChunks: (id1, id2) => mergeChunksApi(id1, id2),
        splitChunk: (id, pos) => splitChunkApi(id, pos),
        toggleChunkVisibility: (id) => toggleChunkVisibilityApi(id),
        toggleChunkExamGate: (id) => toggleChunkExamGateApi(id),
        reloadChunks: () => loadChunks(selectedConcept),
      });
      toast({ variant: "success", title: "Saved", description: "All changes applied successfully" });
    } catch (e) {
      toast({ variant: "danger", title: "Save Failed", description: e.message || "Some changes could not be applied" });
    }
  };

  const handleDiscard = async () => {
    if (!(await dialog.confirm({ title: "Discard Changes", message: "Discard all unsaved changes? This cannot be undone.", variant: "danger", confirmLabel: "Discard" }))) return;
    discardDraft();
  };

  // ── Render ─────────────────────────────────────────────────────────────

  if (loading) return <div style={{ padding: "40px 0", color: "#94A3B8" }}>Loading...</div>;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "calc(100vh - 64px)" }}>

      {/* Header */}
      <div style={{ padding: "12px 20px", borderBottom: "1px solid #E2E8F0", display: "flex", alignItems: "center", gap: "16px", flexShrink: 0, backgroundColor: "#FFFFFF" }}>
        <h2 style={{ fontSize: "18px", fontWeight: 600, color: "#0F172A", textTransform: "capitalize", display: "flex", alignItems: "center", gap: "8px" }}>
          {bookTitle || slug.replace(/_/g, " ")} — Content Editor
          <button
            onClick={async () => {
              const newTitle = prompt("Rename book:", bookTitle || slug.replace(/_/g, " "));
              if (newTitle && newTitle.trim()) {
                try {
                  const { renameBook } = await import("../api/admin");
                  await renameBook(slug, newTitle.trim());
                  setBookTitle(newTitle.trim());
                } catch (e) {
                  alert("Failed to rename book: " + (e.response?.data?.detail || e.message));
                }
              }
            }}
            title="Rename book"
            style={{ background: "none", border: "none", cursor: "pointer", padding: "4px", color: "#94A3B8", fontSize: "14px" }}
          >
            ✎
          </button>
        </h2>
        <span style={{ fontSize: "12px", color: "#22C55E", backgroundColor: "#F0FDF4", padding: "2px 10px", borderRadius: "9999px", fontWeight: 500 }}>Published</span>
        {isDirty && (
          <span style={{ fontSize: "12px", color: "#F97316", backgroundColor: "#FFF7ED", padding: "2px 10px", borderRadius: "9999px", fontWeight: 500, border: "1px solid #FED7AA" }}>
            Draft — unsaved
          </span>
        )}
      </div>

      {/* Three panels */}
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>

        {/* ── Left: section tree ── */}
        <div style={{ width: "300px", flexShrink: 0, borderRight: "1px solid #E2E8F0", overflowY: "auto", padding: "16px", backgroundColor: "#FFFFFF" }}>
          {sections.length === 0 ? (
            <div style={{ fontSize: "13px", color: "#94A3B8" }}>No sections found</div>
          ) : (
            sections.map((chapter) => (
              <div key={chapter.chapter} style={{ marginBottom: "20px" }}>
                <div style={{ fontWeight: 700, fontSize: "12px", color: "#64748B", marginBottom: "8px", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                  Chapter {chapter.chapter}
                </div>
                {chapter.sections.map((sec) => {
                  const sectionNum = sec.section || "";
                  const heading = (sec.display_name && sec.display_name !== sec.section)
                    ? sec.display_name
                    : (sec.heading || sec.concept_id || "");
                  const title = sectionNum && heading && heading !== sectionNum
                    ? `${sectionNum} | ${heading}`
                    : sectionNum || heading;
                  const badges = sectionBadges(title);
                  const isSelected = selectedConcept === sec.concept_id;
                  const prereqCount = (graphEdges || []).filter((e) => e.target === sec.concept_id).length;
                  return (
                    <div key={sec.concept_id}>
                      {/* Section row */}
                      <div
                        onClick={() => loadChunks(sec.concept_id)}
                        style={{
                          padding: "8px 10px",
                          borderRadius: "8px",
                          cursor: "pointer",
                          fontSize: "13px",
                          marginBottom: "2px",
                          display: "flex",
                          alignItems: "flex-start",
                          gap: "6px",
                          flexWrap: "wrap",
                          transition: "background-color 0.15s, opacity 0.15s",
                          opacity: sec.is_hidden ? 0.55 : 1,
                          backgroundColor: sec.is_hidden ? "#FEF2F2" : isSelected ? "#FFF7ED" : "transparent",
                          color: sec.is_hidden ? "#94A3B8" : isSelected ? "#EA580C" : "#0F172A",
                          borderLeft: sec.is_hidden ? "3px solid #FCA5A5" : isSelected ? "3px solid #EA580C" : "3px solid transparent",
                        }}
                      >
                        <span style={{ flex: 1 }}>
                          <strong style={{ fontWeight: 600 }}>{sectionNum}</strong>{" "}
                          <span style={{ fontWeight: 400, color: sec.is_hidden ? "#94A3B8" : isSelected ? "#EA580C" : "#475569" }}>{heading !== sectionNum ? heading : ""}</span>
                          {badges.map((b) => (
                            <SectionBadge key={b.label} label={b.label} cls={b.cls} />
                          ))}
                          {sec.is_hidden && (
                            <span style={{ display: "inline-block", fontSize: "10px", fontWeight: 600, color: "#DC2626", backgroundColor: "#FEE2E2", padding: "1px 5px", borderRadius: "3px", marginLeft: "4px", verticalAlign: "middle" }}>
                              hidden
                            </span>
                          )}
                          {!sec.is_hidden && (sec.hidden_count || 0) > 0 && (
                            <span style={{ display: "inline-block", fontSize: "10px", fontWeight: 600, color: "#B45309", backgroundColor: "#FEF3C7", padding: "1px 5px", borderRadius: "3px", marginLeft: "4px", verticalAlign: "middle" }}>
                              {sec.hidden_count}/{sec.chunk_count} hidden
                            </span>
                          )}
                          {prereqCount > 0 && (
                            <span style={{ fontSize: "10px", color: "#94A3B8", marginLeft: "4px" }}>({prereqCount} prereqs)</span>
                          )}
                        </span>
                        <span style={{ fontSize: "11px", color: "#94A3B8", flexShrink: 0, paddingTop: "2px" }}>
                          {sec.chunk_count}c{sec.image_count > 0 ? ` ${sec.image_count}img` : ""}
                        </span>

                        {/* Section control buttons */}
                        <div
                          style={{ display: "flex", gap: "4px", flexShrink: 0 }}
                          onClick={(e) => e.stopPropagation()}
                        >
                          <button
                            title="Rename section"
                            onClick={() => handleRenameSection(sec)}
                            style={{ padding: "2px 6px", fontSize: "12px", borderRadius: "4px", border: "1px solid #E2E8F0", backgroundColor: "#F8FAFC", color: "#64748B", cursor: "pointer" }}
                          >
                            ✎
                          </button>
                          <button
                            title={sec.is_optional ? "All optional" : (sec.optional_count || 0) > 0 ? `${sec.optional_count}/${sec.chunk_count} optional` : "Toggle optional"}
                            onClick={() => handleToggleSectionOptional(sec)}
                            style={{
                              padding: "2px 6px", fontSize: "10px", fontWeight: 600, borderRadius: "4px", cursor: "pointer",
                              border: sec.is_optional ? "1px solid #FCD34D" : (!sec.is_optional && (sec.optional_count || 0) > 0) ? "1px solid #FDBA74" : "1px solid #E2E8F0",
                              backgroundColor: sec.is_optional ? "#FEF3C7" : (!sec.is_optional && (sec.optional_count || 0) > 0) ? "#FFF7ED" : "#F8FAFC",
                              color: sec.is_optional ? "#92400E" : (!sec.is_optional && (sec.optional_count || 0) > 0) ? "#C2410C" : "#64748B",
                            }}
                          >
                            Opt
                          </button>
                          <button
                            title={sec.exam_disabled ? "All exams disabled" : (sec.exam_disabled_count || 0) > 0 ? `${sec.exam_disabled_count}/${sec.chunk_count} exams disabled` : "Toggle exam gate"}
                            onClick={() => handleToggleSectionExamGate(sec)}
                            style={{
                              padding: "2px 6px", fontSize: "10px", fontWeight: 700, borderRadius: "4px", cursor: "pointer",
                              border: sec.exam_disabled ? "1px solid #FCA5A5" : (!sec.exam_disabled && (sec.exam_disabled_count || 0) > 0) ? "1px solid #FDBA74" : "1px solid #E2E8F0",
                              backgroundColor: sec.exam_disabled ? "#FEE2E2" : (!sec.exam_disabled && (sec.exam_disabled_count || 0) > 0) ? "#FFF7ED" : "#F8FAFC",
                              color: sec.exam_disabled ? "#991B1B" : (!sec.exam_disabled && (sec.exam_disabled_count || 0) > 0) ? "#C2410C" : "#64748B",
                            }}
                          >
                            E
                          </button>
                          <button
                            title={sec.is_hidden ? "Show section" : (sec.hidden_count || 0) > 0 ? `${sec.hidden_count}/${sec.chunk_count} hidden` : "Hide section"}
                            onClick={() => handleToggleSectionVisibility(sec)}
                            style={{
                              padding: "2px 6px", fontSize: "10px", fontWeight: 600, borderRadius: "4px", cursor: "pointer",
                              border: sec.is_hidden ? "1px solid #FCA5A5" : (!sec.is_hidden && (sec.hidden_count || 0) > 0) ? "1px solid #FDBA74" : "1px solid #E2E8F0",
                              backgroundColor: sec.is_hidden ? "#FEE2E2" : (!sec.is_hidden && (sec.hidden_count || 0) > 0) ? "#FFF7ED" : "#F8FAFC",
                              color: sec.is_hidden ? "#991B1B" : (!sec.is_hidden && (sec.hidden_count || 0) > 0) ? "#C2410C" : "#64748B",
                            }}
                          >
                            {sec.is_hidden ? "Show" : "Hide"}
                          </button>
                        </div>
                      </div>

                      {/* Sub-items: chunk headings when this section is selected */}
                      {isSelected && !chunksLoading && draftChunks.length > 0 && (
                        <div style={{ marginBottom: "4px", opacity: sec.is_hidden ? 0.45 : 1 }}>
                          {draftChunks.map((chunk, ci) => {
                            const isActive = activeChunkId === String(chunk.id);
                            const isModifiedLeft = modifiedChunkIds.has(chunk.id);
                            return (
                              <div
                                key={chunk.id}
                                id={`left-chunk-${chunk.id}`}
                                onClick={() => scrollToChunk(chunk.id)}
                                style={{
                                  padding: "4px 8px 4px 20px", fontSize: "12px", cursor: "pointer", borderRadius: "4px",
                                  marginLeft: "8px", marginBottom: "1px", lineHeight: 1.3,
                                  borderLeft: isActive ? "2px solid #EA580C" : chunk.is_hidden ? "2px solid #E2E8F0" : isModifiedLeft ? "2px solid #F97316" : "2px solid #BFDBFE",
                                  color: isActive ? "#EA580C" : chunk.is_hidden ? "#CBD5E1" : "#64748B",
                                  fontWeight: isActive ? 600 : 400,
                                  backgroundColor: isActive ? "#FFF7ED" : "transparent",
                                }}
                              >
                                {chunk.is_hidden && <span style={{ fontSize: "10px", marginRight: "4px", opacity: 0.5 }}>hidden</span>}
                                {!chunk.has_embedding && <span style={{ fontSize: "10px", marginRight: "4px", color: "#F97316" }}>stale</span>}
                                {isModifiedLeft && <span style={{ fontSize: "10px", marginRight: "4px", color: "#F97316" }}>*</span>}
                                {chunk.heading || `Chunk ${ci + 1}`}
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            ))
          )}
        </div>

        {/* ── Center: chunks ── */}
        <div ref={centerRef} style={{ flex: 1, overflowY: "auto", padding: "20px" }}>
          {!selectedConcept ? (
            <div style={{ color: "#94A3B8", textAlign: "center", paddingTop: "64px", fontSize: "14px" }}>
              Select a section from the left panel
            </div>
          ) : chunksLoading ? (
            <div style={{ color: "#94A3B8", fontSize: "14px" }}>Loading chunks...</div>
          ) : draftChunks.length === 0 ? (
            <div style={{ color: "#94A3B8", fontSize: "14px" }}>No chunks found for this section</div>
          ) : (
            draftChunks.map((chunk, i) => {
              const isModified = modifiedChunkIds.has(chunk.id);
              const isTempChunk = String(chunk.id).startsWith("temp-");
              return (
                <div
                  key={chunk.id}
                  id={`chunk-${chunk.id}`}
                  style={{
                    marginBottom: "20px", padding: "20px", borderRadius: "8px", scrollMarginTop: "16px",
                    border: chunk.is_hidden ? "1px dashed #CBD5E1" : "1px solid #E2E8F0",
                    backgroundColor: chunk.is_hidden ? "#F8FAFC" : "#FFFFFF",
                    opacity: chunk.is_hidden ? 0.6 : 1,
                    boxShadow: chunk.is_hidden ? "none" : "0 1px 2px rgba(0,0,0,0.04)",
                    borderLeft: isModified ? "3px solid #F97316" : chunk.is_hidden ? "1px dashed #CBD5E1" : "1px solid #E2E8F0",
                  }}
                >
                  {/* Action toolbar */}
                  <div style={{ display: "flex", gap: "6px", marginBottom: "12px", flexWrap: "wrap" }}>
                    {[
                      { label: "✎", onClick: () => { const newH = window.prompt("New heading:", chunk.heading || ""); if (newH !== null && newH.trim() !== "") editChunk(chunk.id, { heading: newH.trim() }); }, title: "Rename" },
                      { label: "Edit", onClick: () => startEdit(chunk), title: "Edit heading and text" },
                      { label: chunk.is_hidden ? "Show" : "Hide", onClick: () => handleToggleVisibility(chunk.id), title: chunk.is_hidden ? "Show to students" : "Hide from students", active: chunk.is_hidden, activeColor: "#FEF3C7", activeBorder: "#FCD34D", activeText: "#92400E" },
                      { label: chunk.is_optional ? "Required" : "Optional", onClick: () => handleToggleOptional(chunk), title: "Toggle optional", active: chunk.is_optional, activeColor: "#FEF3C7", activeBorder: "#FCD34D", activeText: "#92400E" },
                      { label: chunk.exam_disabled ? "Enable Exam" : "No Exam", onClick: () => handleToggleExamGate(chunk), title: "Toggle exam gate", active: chunk.exam_disabled, activeColor: "#FEE2E2", activeBorder: "#FCA5A5", activeText: "#991B1B" },
                    ].map((btn, bi) => (
                      <button
                        key={bi}
                        onClick={btn.onClick}
                        title={btn.title}
                        style={{
                          padding: "4px 10px", fontSize: "12px", borderRadius: "6px", cursor: "pointer",
                          border: `1px solid ${btn.active ? btn.activeBorder : "#E2E8F0"}`,
                          backgroundColor: btn.active ? btn.activeColor : "#F8FAFC",
                          color: btn.active ? btn.activeText : "#64748B",
                          fontWeight: 500, transition: "background-color 0.15s",
                        }}
                      >
                        {btn.label}
                      </button>
                    ))}
                    <button
                      onClick={() => handleToggleChunkType(chunk)}
                      title={chunk.chunk_type === "exercise" ? "Mark as teaching chunk" : "Mark as exercise chunk"}
                      style={{
                        padding: "2px 8px", fontSize: "11px", borderRadius: "6px", cursor: "pointer", fontWeight: 500,
                        border: chunk.chunk_type === "exercise" ? "1px solid #FCD34D" : "1px solid #E2E8F0",
                        backgroundColor: chunk.chunk_type === "exercise" ? "#FEF3C7" : "#F8FAFC",
                        color: chunk.chunk_type === "exercise" ? "#92400E" : "#64748B",
                      }}
                    >
                      {chunk.chunk_type === "exercise" ? "\u2192 Teaching" : "\u2192 Exercise"}
                    </button>
                    {i < draftChunks.length - 1 && (
                      <button
                        onClick={() => handleMerge(chunk.id, draftChunks[i + 1].id)}
                        title="Merge with the next chunk"
                        style={{ padding: "4px 10px", fontSize: "12px", borderRadius: "6px", cursor: "pointer", border: "1px solid #E2E8F0", backgroundColor: "#F8FAFC", color: "#64748B", fontWeight: 500 }}
                      >
                        Merge ↓
                      </button>
                    )}
                    <button
                      onClick={() => handleSplit(chunk.id)}
                      title="Split this chunk at a character position"
                      style={{ padding: "4px 10px", fontSize: "12px", borderRadius: "6px", cursor: "pointer", border: "1px solid #E2E8F0", backgroundColor: "#F8FAFC", color: "#64748B", fontWeight: 500 }}
                    >
                      Split
                    </button>
                    {i > 0 && !isTempChunk && (
                      <button
                        onClick={async () => {
                          const label = window.prompt("New section label (optional):");
                          if (label === null) return;
                          try {
                            await promoteToSection(selectedConcept, slug, chunk.id, label || undefined);
                            const secRes = await getBookSections(slug);
                            const secData = secRes.data;
                            setSections(secData?.chapters || secData || []);
                            if (secData?.title) setBookTitle(secData.title);
                            loadChunks(selectedConcept);
                            getGraphEdges(slug).then((r) => setGraphEdges(r.data || [])).catch(() => {});
                            getBookGraph(slug).then((r) => {
                              if (r.data) setGraphInfo({ nodes: r.data.nodes?.length || 0, edges: r.data.edges?.length || 0 });
                            }).catch(() => {});
                            toast({ variant: "success", title: "Promoted", description: "Chunk promoted to new section" });
                          } catch (e) {
                            toast({ variant: "danger", title: "Error", description: e.response?.data?.detail || "Failed to promote" });
                          }
                        }}
                        title="Promote this chunk (and all after it) to a new section"
                        style={{
                          padding: "4px 10px", fontSize: "12px", borderRadius: "6px", cursor: "pointer",
                          border: "1px solid #C4B5FD", backgroundColor: "#EDE9FE", color: "#5B21B6", fontWeight: 500,
                        }}
                      >
                        Promote
                      </button>
                    )}
                    {!chunk.has_embedding && !isTempChunk && (
                      <button
                        onClick={() => handleRegenEmbedding(chunk.id)}
                        title="Regenerate embedding for this chunk"
                        style={{
                          padding: "4px 10px", fontSize: "12px", borderRadius: "6px", cursor: "pointer",
                          border: "1px solid #FCD34D", backgroundColor: "#FEF3C7", color: "#92400E", fontWeight: 500,
                        }}
                      >
                        Regen
                      </button>
                    )}
                  </div>

                  {/* Chunk header + inline editor */}
                  {editingChunk === chunk.id ? (
                    <div>
                      <input
                        value={editHeading}
                        onChange={(e) => setEditHeading(e.target.value)}
                        placeholder="Heading"
                        style={{ width: "100%", padding: "6px", marginBottom: "6px", border: "1px solid #E2E8F0", borderRadius: "8px", fontSize: "14px", fontWeight: 700, color: "#0F172A", backgroundColor: "#FFFFFF", outline: "none" }}
                      />
                      <textarea
                        value={editText}
                        onChange={(e) => setEditText(e.target.value)}
                        style={{ width: "100%", minHeight: "200px", padding: "8px", border: "1px solid #E2E8F0", borderRadius: "8px", fontSize: "13px", lineHeight: 1.6, resize: "vertical", color: "#0F172A", backgroundColor: "#FFFFFF", outline: "none" }}
                      />
                      <div style={{ display: "flex", gap: "6px", marginTop: "6px" }}>
                        <button
                          onClick={() => handleSaveEdit(chunk.id)}
                          style={{ padding: "4px 12px", backgroundColor: "#22C55E", color: "#FFFFFF", borderRadius: "9999px", fontSize: "12px", fontWeight: 500, border: "none", cursor: "pointer" }}
                        >
                          Save
                        </button>
                        <button
                          onClick={() => setEditingChunk(null)}
                          style={{ padding: "4px 12px", backgroundColor: "#64748B", color: "#FFFFFF", borderRadius: "9999px", fontSize: "12px", fontWeight: 500, border: "none", cursor: "pointer" }}
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
                      {/* Chunk header: heading + badges */}
                      <div style={{ display: "flex", alignItems: "flex-start", gap: "10px", marginBottom: "10px", flexWrap: "wrap" }}>
                        <h4 style={{ fontSize: "15px", fontWeight: 700, color: "#0F172A", flex: 1, lineHeight: 1.3 }}>
                          {chunk.heading || `Chunk ${i + 1}`}
                          {isModified && !isTempChunk && (
                            <span style={{ fontSize: "10px", color: "#F97316", fontWeight: 600, marginLeft: "8px" }}>Modified</span>
                          )}
                          {isTempChunk && (
                            <span style={{ fontSize: "10px", color: "#3B82F6", fontWeight: 600, marginLeft: "8px" }}>New (split)</span>
                          )}
                        </h4>
                        <div style={{ display: "flex", alignItems: "center", gap: "6px", flexShrink: 0 }}>
                          {chunk.chunk_type && <ChunkTypeBadge type={chunk.chunk_type} />}
                          {chunk.is_optional && (
                            <span style={{ fontSize: "11px", color: "#64748B", fontStyle: "italic" }}>(Optional)</span>
                          )}
                          {chunk.is_hidden && (
                            <span style={{ fontSize: "11px", color: "#94A3B8", fontStyle: "italic" }}>(Hidden)</span>
                          )}
                          {chunk.exam_disabled && (
                            <span style={{ fontSize: "11px", color: "#EF4444", fontStyle: "italic" }}>(No Exam)</span>
                          )}
                          {!chunk.has_embedding && !isTempChunk && (
                            <span style={{ fontSize: "11px", color: "#F97316", fontStyle: "italic" }}>(Stale embedding)</span>
                          )}
                        </div>
                      </div>

                      {/* Chunk text / split UI */}
                      {splittingChunk === chunk.id ? (
                        <div style={{ border: "2px solid #3B82F6", borderRadius: "12px", padding: "12px", backgroundColor: "#EFF6FF" }}>
                          <div style={{ fontSize: "12px", fontWeight: 600, color: "#2563EB", marginBottom: "8px" }}>Click a divider to split at that point:</div>
                          {(chunk.text || "").split("\n\n").map((para, pi, arr) => (
                            <div key={pi}>
                              <p style={{ fontSize: "13px", lineHeight: 1.6, margin: "4px 0", color: "#0F172A" }}>{para}</p>
                              {pi < arr.length - 1 && (
                                <button
                                  onClick={() => handleSplitAt(chunk.id, (chunk.text || "").split("\n\n").slice(0, pi + 1).join("\n\n").length)}
                                  style={{ width: "100%", padding: "4px 0", margin: "4px 0", backgroundColor: "#DBEAFE", border: "1px dashed #3B82F6", borderRadius: "4px", fontSize: "11px", color: "#2563EB", cursor: "pointer" }}
                                >
                                  &#9986; Split here
                                </button>
                              )}
                            </div>
                          ))}
                          <button
                            onClick={() => setSplittingChunk(null)}
                            style={{ marginTop: "8px", padding: "4px 12px", backgroundColor: "#64748B", color: "#FFFFFF", borderRadius: "9999px", fontSize: "12px", border: "none", cursor: "pointer" }}
                          >
                            Cancel
                          </button>
                        </div>
                      ) : (
                        <p style={{ fontSize: "14px", lineHeight: 1.6, color: "#64748B", whiteSpace: "pre-wrap" }}>
                          {chunk.text}
                        </p>
                      )}

                      {/* Images (only for server-backed chunks) */}
                      {!isTempChunk && chunk.images?.length > 0 && (
                        <div style={{ marginTop: "14px", display: "flex", flexWrap: "wrap", gap: "12px" }}>
                          {chunk.images.map((img, j) => (
                            <div key={j} style={{ maxWidth: "360px" }}>
                              <img
                                src={resolveImageUrl(img.image_url)}
                                alt={img.caption || "Image"}
                                style={{ maxWidth: "100%", maxHeight: "280px", borderRadius: "8px", objectFit: "contain", border: "1px solid #F1F5F9" }}
                              />
                              {img.caption && (
                                <p style={{ fontSize: "12px", color: "#64748B", marginTop: "4px", lineHeight: 1.3 }}>{img.caption}</p>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </>
                  )}
                </div>
              );
            })
          )}
        </div>

        {/* ── Right: prerequisite editor ── */}
        <div style={{ width: "300px", flexShrink: 0, borderLeft: "1px solid #E2E8F0", padding: "16px", overflowY: "auto", backgroundColor: "#FFFFFF" }}>
          <PrereqAccordion
            slug={slug}
            graphEdges={graphEdges}
            sections={sections}
            allConcepts={allConcepts}
            graphInfo={graphInfo}
            onEdgesChanged={() => getGraphEdges(slug).then((r) => setGraphEdges(r.data || [])).catch(() => {})}
          />
        </div>
      </div>

      {/* Bottom action bar */}
      {isDirty ? (
        <div style={{ padding: "16px 24px", borderTop: "1px solid #E2E8F0", display: "flex", justifyContent: "space-between", alignItems: "center", backgroundColor: "#FFF7ED", flexShrink: 0 }}>
          <div style={{ fontSize: "13px", color: "#F97316", fontWeight: 500 }}>
            {modifiedChunkIds.size + pendingStructural.length} unsaved change{(modifiedChunkIds.size + pendingStructural.length) !== 1 ? "s" : ""}
          </div>
          <div style={{ display: "flex", gap: "10px" }}>
            <button
              onClick={handleDiscard}
              disabled={saveStatus === "saving"}
              style={{ padding: "10px 24px", backgroundColor: "#64748B", color: "#FFFFFF", borderRadius: "9999px", fontSize: "14px", fontWeight: 600, border: "none", cursor: saveStatus === "saving" ? "not-allowed" : "pointer", opacity: saveStatus === "saving" ? 0.6 : 1 }}
            >
              Discard
            </button>
            <button
              onClick={handleSaveAll}
              disabled={saveStatus === "saving"}
              style={{ padding: "10px 24px", backgroundColor: "#22C55E", color: "#FFFFFF", borderRadius: "9999px", fontSize: "14px", fontWeight: 600, border: "none", cursor: saveStatus === "saving" ? "not-allowed" : "pointer", opacity: saveStatus === "saving" ? 0.7 : 1 }}
            >
              {saveStatus === "saving" ? "Saving..." : "Save Changes"}
            </button>
          </div>
        </div>
      ) : (
        <div style={{ padding: "16px 24px", borderTop: "1px solid #E2E8F0", display: "flex", justifyContent: "space-between", alignItems: "center", backgroundColor: "#FFFFFF", flexShrink: 0 }}>
          {/* Left: stale embedding status */}
          <div style={{ fontSize: "13px" }}>
            {selectedConcept ? (
              staleCount > 0 ? (
                <span style={{ color: "#F97316", fontWeight: 500 }}>
                  {staleCount} stale embedding{staleCount !== 1 ? "s" : ""}
                </span>
              ) : (
                <span style={{ color: "#22C55E", fontWeight: 500 }}>All embeddings OK</span>
              )
            ) : (
              <span style={{ color: "#94A3B8" }}>Select a section to edit</span>
            )}
          </div>

          {/* Right: action buttons */}
          <div style={{ display: "flex", gap: "10px" }}>
            <button
              onClick={handleRegenAllStale}
              disabled={regenAllBusy || !selectedConcept || staleCount === 0}
              style={{
                padding: "10px 24px", backgroundColor: (!selectedConcept || staleCount === 0) ? "#CBD5E1" : "#EA580C",
                color: "#FFFFFF", borderRadius: "9999px", fontSize: "14px", fontWeight: 600, border: "none",
                cursor: (regenAllBusy || !selectedConcept || staleCount === 0) ? "not-allowed" : "pointer",
                opacity: regenAllBusy ? 0.7 : 1, transition: "background-color 0.15s",
              }}
            >
              {regenAllBusy ? "Regenerating..." : "Regenerate Embeddings"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
