import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useToast } from "../components/ui/Toast";
import { useDialog } from "../context/DialogProvider";
import {
  getBookSections, getBookChunks, getBookGraph, publishBook, dropBook, getAdminBooks,
  getBookStatus,
  updateChunk, toggleChunkVisibility, toggleChunkExamGate, mergeChunks, splitChunk,
  renameSection, toggleSectionOptional, toggleSectionExamGate, toggleSectionVisibility,
  getGraphEdges, getGraphOverrides, modifyGraphEdge, deleteGraphOverride,
  promoteToSection,
} from "../api/admin";
import { resolveImageUrl } from "../api/client";

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

// ── Main component ─────────────────────────────────────────────────────────

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

  // Also build from allConcepts (which has {concept_id, label} objects in ReviewPage)
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

export default function AdminReviewPage() {
  const { slug } = useParams();
  const navigate = useNavigate();
  const { toast } = useToast();
  const dialog = useDialog();

  // Core data
  const [sections, setSections] = useState([]);
  const [selectedConcept, setSelectedConcept] = useState(null);
  const [chunks, setChunks] = useState([]);
  const [graphInfo, setGraphInfo] = useState(null);
  const [bookSubject, setBookSubject] = useState(null);
  const [bookStatus, setBookStatus] = useState(null);
  const [overrides, setOverrides] = useState([]);
  const [allConcepts, setAllConcepts] = useState([]);
  const [graphEdges, setGraphEdges] = useState([]);
  const [splittingChunk, setSplittingChunk] = useState(null);

  // Loading flags
  const [loading, setLoading] = useState(true);
  const [chunksLoading, setChunksLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);

  // Inline chunk editing
  const [editingChunk, setEditingChunk] = useState(null);
  const [editHeading, setEditHeading] = useState("");
  const [editText, setEditText] = useState("");

  // Graph editor inputs (uncontrolled — accessed via refs)
  const edgeSourceRef = useRef(null);
  const edgeTargetRef = useRef(null);

  // Scroll-sync: track which chunk is visible in the center panel
  const [activeChunkId, setActiveChunkId] = useState(null);
  const centerRef = useRef(null);

  // ── Initial load ───────────────────────────────────────────────────────

  useEffect(() => {
    Promise.all([
      getBookSections(slug),
      getBookGraph(slug).catch(() => ({ data: null })),
      getAdminBooks().catch(() => ({ data: [] })),
    ]).then(([secRes, graphRes, booksRes]) => {
      const chaptersArr = secRes.data?.chapters || secRes.data || [];
      setSections(chaptersArr);
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
      const book = booksRes.data.find((b) => b.slug === slug);
      if (book) {
        setBookSubject(book.subject);
        setBookStatus(book.status);
      }
      setLoading(false);
    }).catch((e) => { console.error(e); setLoading(false); });

    loadOverrides();
    getGraphEdges(slug).then((r) => setGraphEdges(r.data || [])).catch(() => {});
  }, [slug]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Poll while pipeline is PROCESSING ─────────────────────────────────

  useEffect(() => {
    if (bookStatus !== "PROCESSING") return;
    const id = setInterval(() => {
      getBookStatus(slug).then((r) => {
        const s = r.data?.status;
        if (s) setBookStatus(s);
        if (s && s !== "PROCESSING") {
          Promise.all([
            getBookSections(slug),
            getBookGraph(slug).catch(() => ({ data: null })),
          ]).then(([secRes, graphRes]) => {
            const chaptersArr = secRes.data?.chapters || secRes.data || [];
            setSections(chaptersArr);
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
          });
          loadOverrides();
          getGraphEdges(slug).then((r) => setGraphEdges(r.data || [])).catch(() => {});
        }
      }).catch(() => {});
    }, 10000);
    return () => clearInterval(id);
  }, [bookStatus, slug]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Chunk loading ──────────────────────────────────────────────────────

  const loadChunks = useCallback((conceptId) => {
    setSelectedConcept(conceptId);
    setChunks([]);
    setEditingChunk(null);
    setChunksLoading(true);
    getBookChunks(slug, conceptId)
      .then((r) => setChunks(r.data))
      .catch(console.error)
      .finally(() => setChunksLoading(false));
  }, [slug]);

  const scrollToChunk = useCallback((chunkId) => {
    const el = document.getElementById(`chunk-${chunkId}`);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  // ── Listen for undo/redo performed from AdminTopBar ────────────────────

  useEffect(() => {
    const handleAuditChanged = () => {
      // Refetch sections list so sidebar reflects server state after undo/redo
      getBookSections(slug).then((secRes) => {
        const chaptersArr = secRes.data?.chapters || secRes.data || [];
        setSections(chaptersArr);
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
      }).catch((e) => { console.error("[admin] failed to refetch sections after audit change", e); });
      // Refetch chunks for the currently selected section
      if (selectedConcept) {
        loadChunks(selectedConcept);
      }
      toast({ variant: "info", title: "Content updated", description: "Re-fetched from server." });
    };

    window.addEventListener("admin:audit-changed", handleAuditChanged);
    return () => window.removeEventListener("admin:audit-changed", handleAuditChanged);
  }, [slug, selectedConcept, loadChunks]); // eslint-disable-line react-hooks/exhaustive-deps

  // Scroll-sync: observe which chunk is in view and highlight in left panel
  useEffect(() => {
    const container = centerRef.current;
    if (!container || chunks.length === 0) return;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            const id = entry.target.id.replace("chunk-", "");
            setActiveChunkId(id);
            // Also scroll the left panel sub-item into view
            const leftEl = document.getElementById(`left-chunk-${id}`);
            if (leftEl) leftEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
            break;
          }
        }
      },
      { root: container, rootMargin: "-10% 0px -60% 0px", threshold: 0 }
    );
    chunks.forEach((c) => {
      const el = document.getElementById(`chunk-${c.id}`);
      if (el) observer.observe(el);
    });
    return () => observer.disconnect();
  }, [chunks]);

  // ── Chunk handlers ─────────────────────────────────────────────────────

  const startEdit = (chunk) => {
    setEditingChunk(chunk.id);
    setEditHeading(chunk.heading || "");
    setEditText(chunk.text || "");
  };

  const handleSaveEdit = async (chunkId) => {
    try {
      await updateChunk(chunkId, { heading: editHeading, text: editText });
      setEditingChunk(null);
      loadChunks(selectedConcept);
      // Also refresh sections so left panel shows updated heading
      getBookSections(slug).then((r) => setSections(r.data?.chapters || r.data || [])).catch(() => {});
    } catch (e) {
      toast({ variant: "danger", title: "Error", description: e.response?.data?.detail || "Failed to save" });
    }
  };

  const handleRenameChunkHeading = async (chunk) => {
    const newHeading = window.prompt("New heading:", chunk.heading || "");
    if (newHeading === null || newHeading.trim() === "") return;
    try {
      await updateChunk(chunk.id, { heading: newHeading.trim() });
      loadChunks(selectedConcept);
      getBookSections(slug).then((r) => setSections(r.data?.chapters || r.data || [])).catch(() => {});
    } catch (e) {
      toast({ variant: "danger", title: "Error", description: e.response?.data?.detail || "Failed to rename heading" });
    }
  };

  const handleToggleVisibility = async (chunkId) => {
    try {
      const chunk = chunks.find((c) => c.id === chunkId);
      if (chunk && chunk.is_hidden) {
        await updateChunk(chunkId, { is_hidden: false, chunk_type_locked: true });
      } else {
        await toggleChunkVisibility(chunkId);
      }
      loadChunks(selectedConcept);
    } catch (e) {
      toast({ variant: "danger", title: "Error", description: e.response?.data?.detail || e.message || "Failed to toggle visibility" });
    }
  };

  const handleToggleOptional = async (chunk) => {
    try {
      await updateChunk(chunk.id, { is_optional: !chunk.is_optional });
      loadChunks(selectedConcept);
    } catch (e) {
      toast({ variant: "danger", title: "Error", description: e.response?.data?.detail || e.message || "Failed to toggle optional" });
    }
  };

  const handleToggleExamGate = async (chunk) => {
    try {
      await toggleChunkExamGate(chunk.id);
      loadChunks(selectedConcept);
    } catch (e) {
      toast({ variant: "danger", title: "Error", description: e.response?.data?.detail || e.message || "Failed to toggle exam gate" });
    }
  };

  const handleToggleChunkType = async (chunk) => {
    const nextType = chunk.chunk_type === "exercise" ? "teaching" : "exercise";
    try {
      await updateChunk(chunk.id, { chunk_type: nextType, chunk_type_locked: true });
      loadChunks(selectedConcept);
    } catch (e) {
      toast({ variant: "danger", title: "Error", description: e.response?.data?.detail || e.message || "Failed to toggle chunk type" });
    }
  };

  const handleMerge = async (id1, id2) => {
    if (!(await dialog.confirm({ title: "Merge Chunks", message: "Merge these two chunks? This combines their text and cannot be easily undone.", variant: "danger", confirmLabel: "Confirm" }))) return;
    try {
      await mergeChunks(id1, id2);
      loadChunks(selectedConcept);
    } catch (e) {
      toast({ variant: "danger", title: "Error", description: e.response?.data?.detail || "Failed to merge" });
    }
  };

  const handleSplit = (chunkId) => {
    setSplittingChunk(chunkId);
  };

  const handleSplitAt = async (chunkId, position) => {
    try {
      await splitChunk(chunkId, position);
      setSplittingChunk(null);
      loadChunks(selectedConcept);
    } catch (e) {
      toast({ variant: "danger", title: "Error", description: e.response?.data?.detail || "Failed to split" });
    }
  };

  const handlePromoteToSection = async (chunk) => {
    const label = window.prompt(
      "New section label (leave blank to use chunk heading):",
      chunk.heading || ""
    );
    if (label === null) return;
    try {
      await promoteToSection(selectedConcept, slug, chunk.id, label);
      const [secRes] = await Promise.all([
        getBookSections(slug),
        getBookGraph(slug).catch(() => ({ data: null })),
      ]);
      const chaptersArr = secRes.data?.chapters || secRes.data || [];
      setSections(chaptersArr);
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
      loadChunks(selectedConcept);
      getGraphEdges(slug).then((r) => setGraphEdges(r.data || [])).catch(() => {});
      loadOverrides();
    } catch (e) {
      toast({ variant: "danger", title: "Error", description: e.response?.data?.detail || e.message || "Failed to promote" });
    }
  };

  // ── Section handlers ───────────────────────────────────────────────────

  const handleRenameSection = async (sec) => {
    const newName = window.prompt("New section name:", sec.heading || sec.section || "");
    if (!newName || newName.trim() === "") return;
    try {
      await renameSection(sec.concept_id, slug, newName.trim());
      const secRes = await getBookSections(slug);
      setSections(secRes.data?.chapters || secRes.data || []);
      // Refresh chunks too so left panel sub-items update
      if (selectedConcept) loadChunks(selectedConcept);
    } catch (e) {
      toast({ variant: "danger", title: "Error", description: e.response?.data?.detail || "Failed to rename" });
    }
  };

  const handleToggleSectionOptional = async (sec) => {
    try {
      await toggleSectionOptional(sec.concept_id, slug, !sec.is_optional);
      getBookSections(slug).then((r) => setSections(r.data?.chapters || r.data || [])).catch(console.error);
    } catch (e) {
      toast({ variant: "danger", title: "Error", description: e.response?.data?.detail || e.message || "Failed to toggle optional" });
    }
  };

  const handleToggleSectionExamGate = async (sec) => {
    try {
      await toggleSectionExamGate(sec.concept_id, slug, !sec.exam_disabled);
      getBookSections(slug).then((r) => setSections(r.data?.chapters || r.data || [])).catch(console.error);
    } catch (e) {
      toast({ variant: "danger", title: "Error", description: e.response?.data?.detail || e.message || "Failed to toggle exam gate" });
    }
  };

  const handleToggleSectionVisibility = async (sec) => {
    try {
      await toggleSectionVisibility(sec.concept_id, slug, !sec.is_hidden);
      getBookSections(slug).then((r) => setSections(r.data?.chapters || r.data || [])).catch(console.error);
    } catch (e) {
      toast({ variant: "danger", title: "Error", description: e.response?.data?.detail || e.message || "Failed to toggle section visibility" });
    }
  };

  // ── Graph handlers ─────────────────────────────────────────────────────

  const loadOverrides = () => {
    getGraphOverrides(slug).then((r) => setOverrides(r.data)).catch(() => {});
  };

  const handleAddEdge = async () => {
    const source = edgeSourceRef.current?.value?.trim();
    const target = edgeTargetRef.current?.value?.trim();
    if (!source || !target) return;
    try {
      await modifyGraphEdge(slug, "add_edge", source, target);
      loadOverrides();
      getGraphEdges(slug).then((r) => setGraphEdges(r.data || [])).catch(() => {});
      if (edgeSourceRef.current) edgeSourceRef.current.value = "";
      if (edgeTargetRef.current) edgeTargetRef.current.value = "";
    } catch (e) {
      toast({ variant: "danger", title: "Error", description: e.response?.data?.detail || "Failed — may create cycle" });
    }
  };

  const handleRemoveEdge = async () => {
    const source = edgeSourceRef.current?.value?.trim();
    const target = edgeTargetRef.current?.value?.trim();
    if (!source || !target) return;
    try {
      await modifyGraphEdge(slug, "remove_edge", source, target);
      loadOverrides();
      getGraphEdges(slug).then((r) => setGraphEdges(r.data || [])).catch(() => {});
      if (edgeSourceRef.current) edgeSourceRef.current.value = "";
      if (edgeTargetRef.current) edgeTargetRef.current.value = "";
    } catch (e) {
      toast({ variant: "danger", title: "Error", description: e.response?.data?.detail || "Failed to remove edge" });
    }
  };

  const handleDeleteOverride = async (id) => {
    try {
      await deleteGraphOverride(slug, id);
      loadOverrides();
      getGraphEdges(slug).then((r) => setGraphEdges(r.data || [])).catch(() => {});
    } catch (e) {
      toast({ variant: "danger", title: "Error", description: e.response?.data?.detail || e.message || "Failed to delete override" });
    }
  };

  // ── Proceed / Drop ─────────────────────────────────────────────────────

  const handleDrop = async () => {
    if (!(await dialog.confirm({ title: "Drop Book", message: "Drop this book? This permanently deletes all extracted data.", variant: "danger", confirmLabel: "Confirm" }))) return;
    setActionLoading(true);
    dropBook(slug)
      .then(() => navigate(bookSubject ? `/admin/subjects/${bookSubject}` : "/admin"))
      .catch((e) => { toast({ variant: "danger", title: "Error", description: e.response?.data?.detail || "Failed" }); setActionLoading(false); });
  };

  const handleProceed = async () => {
    if (!(await dialog.confirm({ title: "Publish Book", message: "Publish this book? Students will be able to access it.", variant: "primary", confirmLabel: "Confirm" }))) return;
    setActionLoading(true);
    publishBook(slug)
      .then(() => navigate(bookSubject ? `/admin/subjects/${bookSubject}` : "/admin"))
      .catch((e) => { toast({ variant: "danger", title: "Error", description: e.response?.data?.detail || "Failed to publish" }); setActionLoading(false); });
  };

  // ── Render ─────────────────────────────────────────────────────────────

  if (loading) return <div style={{ padding: "40px 0", color: "#94A3B8" }}>Loading...</div>;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "calc(100vh - 64px)" }}>

      {/* Header */}
      <div style={{ padding: "12px 20px", borderBottom: "1px solid #E2E8F0", display: "flex", alignItems: "center", gap: "16px", flexShrink: 0, backgroundColor: "#FFFFFF" }}>
        <h2 style={{ fontSize: "18px", fontWeight: 600, color: "#0F172A", textTransform: "capitalize" }}>
          {slug.replace(/_/g, " ")} — Review
        </h2>
        {bookStatus === "PROCESSING" && (
          <span style={{ fontSize: "12px", color: "#F97316", backgroundColor: "#FFF7ED", padding: "2px 10px", borderRadius: "9999px", fontWeight: 500 }}>Processing...</span>
        )}
      </div>

      {/* Three panels */}
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>

        {/* ── Left: section tree ── */}
        <div style={{ width: "300px", flexShrink: 0, borderRight: "1px solid #E2E8F0", overflowY: "auto", padding: "16px", backgroundColor: "#FFFFFF" }}>
          {sections.length === 0 ? (
            bookStatus === "PROCESSING" ? (
              <div style={{ fontSize: "13px", color: "#F97316", padding: "12px", backgroundColor: "#FFF7ED", borderRadius: "12px", textAlign: "center" }}>
                Pipeline is processing... sections will appear when extraction completes.
              </div>
            ) : (
              <div style={{ fontSize: "13px", color: "#94A3B8" }}>No sections found</div>
            )
          ) : (
            sections.map((chapter) => (
              <div key={chapter.chapter} style={{ marginBottom: "20px" }}>
                <div style={{ fontWeight: 700, fontSize: "12px", color: "#64748B", marginBottom: "8px", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                  Chapter {chapter.chapter}
                </div>
                {chapter.sections.map((sec) => {
                  const sectionNum = sec.section || "";
                  const heading = sec.heading || sec.concept_id || "";
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
                          transition: "background-color 0.15s",
                          backgroundColor: isSelected ? "#FFF7ED" : "transparent",
                          color: isSelected ? "#EA580C" : "#0F172A",
                          borderLeft: isSelected ? "3px solid #EA580C" : "3px solid transparent",
                        }}
                      >
                        <span style={{ flex: 1 }}>
                          <strong style={{ fontWeight: 600 }}>{sectionNum}</strong>{" "}
                          <span style={{ fontWeight: 400, color: isSelected ? "#EA580C" : "#475569" }}>{heading !== sectionNum ? heading : ""}</span>
                          {badges.map((b) => (
                            <SectionBadge key={b.label} label={b.label} cls={b.cls} />
                          ))}
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
                            title="Toggle optional"
                            onClick={() => handleToggleSectionOptional(sec)}
                            style={{
                              padding: "2px 6px", fontSize: "10px", fontWeight: 600, borderRadius: "4px", cursor: "pointer",
                              border: sec.is_optional ? "1px solid #FCD34D" : "1px solid #E2E8F0",
                              backgroundColor: sec.is_optional ? "#FEF3C7" : "#F8FAFC",
                              color: sec.is_optional ? "#92400E" : "#64748B",
                            }}
                          >
                            Opt
                          </button>
                          <button
                            title="Toggle exam gate"
                            onClick={() => handleToggleSectionExamGate(sec)}
                            style={{
                              padding: "2px 6px", fontSize: "10px", fontWeight: 700, borderRadius: "4px", cursor: "pointer",
                              border: sec.exam_disabled ? "1px solid #FCA5A5" : "1px solid #E2E8F0",
                              backgroundColor: sec.exam_disabled ? "#FEE2E2" : "#F8FAFC",
                              color: sec.exam_disabled ? "#991B1B" : "#64748B",
                            }}
                          >
                            E
                          </button>
                          <button
                            title={sec.is_hidden ? "Show section" : "Hide section"}
                            onClick={() => handleToggleSectionVisibility(sec)}
                            style={{
                              padding: "2px 6px", fontSize: "10px", fontWeight: 600, borderRadius: "4px", cursor: "pointer",
                              border: sec.is_hidden ? "1px solid #FCA5A5" : "1px solid #E2E8F0",
                              backgroundColor: sec.is_hidden ? "#FEE2E2" : "#F8FAFC",
                              color: sec.is_hidden ? "#991B1B" : "#64748B",
                            }}
                          >
                            {sec.is_hidden ? "Show" : "Hide"}
                          </button>
                        </div>
                      </div>

                      {/* Sub-items: chunk headings when this section is selected */}
                      {isSelected && !chunksLoading && chunks.length > 0 && (
                        <div style={{ marginBottom: "4px" }}>
                          {chunks.map((chunk, ci) => {
                            const isActive = activeChunkId === chunk.id;
                            return (
                              <div
                                key={chunk.id}
                                id={`left-chunk-${chunk.id}`}
                                onClick={() => scrollToChunk(chunk.id)}
                                style={{
                                  padding: "4px 8px 4px 20px", fontSize: "12px", cursor: "pointer", borderRadius: "4px",
                                  marginLeft: "8px", marginBottom: "1px", lineHeight: 1.3,
                                  borderLeft: isActive ? "2px solid #EA580C" : chunk.is_hidden ? "2px solid #E2E8F0" : "2px solid #BFDBFE",
                                  color: isActive ? "#EA580C" : chunk.is_hidden ? "#CBD5E1" : "#64748B",
                                  fontWeight: isActive ? 600 : 400,
                                  backgroundColor: isActive ? "#FFF7ED" : "transparent",
                                }}
                              >
                                {chunk.is_hidden && <span style={{ fontSize: "10px", marginRight: "4px", opacity: 0.5 }}>hidden</span>}
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
          ) : chunks.length === 0 ? (
            <div style={{ color: "#94A3B8", fontSize: "14px" }}>No chunks found for this section</div>
          ) : (
            chunks.map((chunk, i) => (
              <div
                key={chunk.id}
                id={`chunk-${chunk.id}`}
                style={{
                  marginBottom: "20px", padding: "20px", borderRadius: "8px", scrollMarginTop: "16px",
                  border: chunk.is_hidden ? "1px dashed #CBD5E1" : "1px solid #E2E8F0",
                  backgroundColor: chunk.is_hidden ? "#F8FAFC" : "#FFFFFF",
                  opacity: chunk.is_hidden ? 0.6 : 1,
                  boxShadow: chunk.is_hidden ? "none" : "0 1px 2px rgba(0,0,0,0.04)",
                }}
              >
                {/* Action toolbar */}
                <div style={{ display: "flex", gap: "6px", marginBottom: "12px", flexWrap: "wrap" }}>
                  {[
                    { label: "✎", onClick: () => handleRenameChunkHeading(chunk), title: "Rename" },
                    { label: "Edit", onClick: () => startEdit(chunk), title: "Edit heading and text" },
                    { label: chunk.is_hidden ? "Show" : "Hide", onClick: () => handleToggleVisibility(chunk.id), title: chunk.is_hidden ? "Show to students" : "Hide from students", active: chunk.is_hidden, activeColor: "#FEF3C7", activeBorder: "#FCD34D", activeText: "#92400E" },
                    { label: chunk.is_optional ? "Required" : "Optional", onClick: () => handleToggleOptional(chunk), title: "Toggle optional", active: chunk.is_optional, activeColor: "#FEF3C7", activeBorder: "#FCD34D", activeText: "#92400E" },
                    { label: chunk.exam_disabled ? "Enable Exam" : "No Exam", onClick: () => handleToggleExamGate(chunk), title: "Toggle exam gate", active: chunk.exam_disabled, activeColor: "#FEE2E2", activeBorder: "#FCA5A5", activeText: "#991B1B" },
                  ].map((btn, i) => (
                    <button
                      key={i}
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
                  {i < chunks.length - 1 && (
                    <button
                      onClick={() => handleMerge(chunk.id, chunks[i + 1].id)}
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
                  {i > 0 && (
                    <button
                      onClick={() => handlePromoteToSection(chunk)}
                      title="Promote this chunk (and all after it) to a new section"
                      style={{ padding: "4px 10px", fontSize: "12px", borderRadius: "6px", cursor: "pointer", border: "1px solid #93C5FD", backgroundColor: "#DBEAFE", color: "#1D4ED8", fontWeight: 500 }}
                    >
                      ↑ Section
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
                      </div>
                    </div>

                    {/* Chunk text / split UI */}
                    {splittingChunk === chunk.id ? (
                      <div style={{ border: "2px solid #3B82F6", borderRadius: "12px", padding: "12px", backgroundColor: "#EFF6FF" }}>
                        <div style={{ fontSize: "12px", fontWeight: 600, color: "#2563EB", marginBottom: "8px" }}>Click a divider to split at that point:</div>
                        {chunk.text.split("\n\n").map((para, pi, arr) => (
                          <div key={pi}>
                            <p style={{ fontSize: "13px", lineHeight: 1.6, margin: "4px 0", color: "#0F172A" }}>{para}</p>
                            {pi < arr.length - 1 && (
                              <button
                                onClick={() => handleSplitAt(chunk.id, chunk.text.split("\n\n").slice(0, pi + 1).join("\n\n").length)}
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

                    {/* Images */}
                    {chunk.images?.length > 0 && (
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
            ))
          )}
        </div>

        {/* ── Right: graph editor ── */}
        <div style={{ width: "300px", flexShrink: 0, borderLeft: "1px solid #E2E8F0", padding: "16px", overflowY: "auto", backgroundColor: "#FFFFFF" }}>
          <PrereqAccordion slug={slug} graphEdges={graphEdges} sections={sections} allConcepts={allConcepts} graphInfo={graphInfo} onEdgesChanged={() => getGraphEdges(slug).then((r) => setGraphEdges(r.data || [])).catch(() => {})} />
        </div>
      </div>

      {/* Bottom action bar */}
      <div style={{ padding: "16px 24px", borderTop: "1px solid #E2E8F0", display: "flex", justifyContent: "space-between", backgroundColor: "#FFFFFF", flexShrink: 0 }}>
        <button
          onClick={handleDrop}
          disabled={actionLoading || bookStatus === "PROCESSING"}
          style={{
            padding: "10px 24px", backgroundColor: "#EF4444", color: "#FFFFFF", borderRadius: "9999px",
            fontSize: "14px", fontWeight: 600, border: "none", cursor: (actionLoading || bookStatus === "PROCESSING") ? "not-allowed" : "pointer",
            opacity: (actionLoading || bookStatus === "PROCESSING") ? 0.6 : 1, transition: "background-color 0.15s",
          }}
        >
          Drop (Wipe Everything)
        </button>
        <button
          onClick={handleProceed}
          disabled={actionLoading || bookStatus === "PROCESSING"}
          style={{
            padding: "10px 24px", backgroundColor: "#22C55E", color: "#FFFFFF", borderRadius: "9999px",
            fontSize: "14px", fontWeight: 600, border: "none", cursor: (actionLoading || bookStatus === "PROCESSING") ? "not-allowed" : "pointer",
            opacity: (actionLoading || bookStatus === "PROCESSING") ? 0.6 : 1, transition: "background-color 0.15s",
          }}
        >
          Proceed — Publish
        </button>
      </div>
    </div>
  );
}
