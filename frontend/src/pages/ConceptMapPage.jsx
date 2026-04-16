import { useState, useMemo, useEffect, useRef, useCallback } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { trackEvent } from "../utils/analytics";
import { useConceptMap } from "../hooks/useConceptMap";
import { useStudent } from "../context/StudentContext";
import ConceptGraph from "../components/conceptmap/ConceptGraph";
import Breadcrumb from "../components/ui/Breadcrumb";
import { ProgressBar } from "../components/ui";
import { formatConceptTitle } from "../utils/formatConceptTitle";
import { getReviewDue } from "../api/students";
import { getAvailableBooks, getGraphFull } from "../api/concepts";
import { motion, AnimatePresence } from "framer-motion";
import { staggerContainer, staggerItem } from "../theme/themes";
import {
  Loader, Play, CheckCircle, Lock, BookOpen, Trophy, Target,
  AlertTriangle, RefreshCw, ChevronRight, ArrowLeft, GraduationCap, Library,
  Heart, Atom, FlaskConical, Leaf,
} from "lucide-react";

/* ── Design tokens ── */
const SUBJECT_COLORS = [
  { bg: "#EFF6FF", text: "#2563EB", accent: "#3B82F6", glow: "rgba(59,130,246,0.15)", bar: "primary" },
  { bg: "#F0FDF4", text: "#16A34A", accent: "#22C55E", glow: "rgba(34,197,94,0.15)", bar: "success" },
  { bg: "#FAF5FF", text: "#9333EA", accent: "#A855F7", glow: "rgba(168,85,247,0.15)", bar: "primary" },
  { bg: "#FFF7ED", text: "#EA580C", accent: "#F97316", glow: "rgba(249,115,22,0.15)", bar: "primary" },
  { bg: "#FFF1F2", text: "#E11D48", accent: "#F43F5E", glow: "rgba(244,63,94,0.15)", bar: "danger" },
  { bg: "#F0F9FF", text: "#0369A1", accent: "#0EA5E9", glow: "rgba(14,165,233,0.15)", bar: "primary" },
];

const SUBJECT_ICONS = {
  mathematics: GraduationCap,
  nursing: Heart,
  physics: Atom,
  chemistry: FlaskConical,
  biology: Leaf,
};

const slideVariants = {
  enter: (dir) => ({ x: dir === "forward" ? 50 : -50, opacity: 0, scale: 0.98 }),
  center: { x: 0, opacity: 1, scale: 1 },
  exit: (dir) => ({ x: dir === "forward" ? -50 : 50, opacity: 0, scale: 0.98 }),
};

const slideTransition = { type: "spring", stiffness: 320, damping: 32 };

/* ── Circular progress ring ── */
function ProgressRing({ pct = 0, size = 52, stroke = 4, color = "#3B82F6", trackColor = "var(--color-border)" }) {
  const r = (size - stroke) / 2;
  const circ = 2 * Math.PI * r;
  const offset = circ - (pct / 100) * circ;
  return (
    <svg width={size} height={size} style={{ transform: "rotate(-90deg)", flexShrink: 0 }}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={trackColor} strokeWidth={stroke} opacity={0.3} />
      <motion.circle
        cx={size / 2} cy={size / 2} r={r} fill="none"
        stroke={color} strokeWidth={stroke} strokeLinecap="round"
        strokeDasharray={circ}
        initial={{ strokeDashoffset: circ }}
        animate={{ strokeDashoffset: offset }}
        transition={{ type: "spring", stiffness: 60, damping: 15, delay: 0.2 }}
      />
    </svg>
  );
}

/* ── Skeleton shimmer ── */
function Shimmer({ w, h = 10, r = 6, style: extra }) {
  return (
    <div style={{
      width: w, height: h, borderRadius: r,
      background: "linear-gradient(90deg, var(--color-border) 25%, var(--color-bg) 50%, var(--color-border) 75%)",
      backgroundSize: "200% 100%",
      animation: "shimmer 1.6s ease-in-out infinite",
      ...extra,
    }} />
  );
}

/* ═══════════════════════════════════════════════════════════════
   Main Page
   ═══════════════════════════════════════════════════════════════ */

export default function ConceptMapPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { student, masteredConcepts } = useStudent();

  /* ── View state ── */
  const [viewLevel, setViewLevel] = useState("subjects");
  const [selectedSubject, setSelectedSubject] = useState(null);
  const [selectedBook, setSelectedBook] = useState(null);
  const directionRef = useRef("forward");

  /* ── Data state ── */
  const [availableBooks, setAvailableBooks] = useState([]);
  const [booksLoaded, setBooksLoaded] = useState(false);
  const [bookGraphStats, setBookGraphStats] = useState({});
  const [statsLoading, setStatsLoading] = useState(false);
  const graphCacheRef = useRef({});

  /* ── Graph (Level 3 only) ── */
  const activeBook = viewLevel === "graph" ? selectedBook : null;
  const { nodes, edges, nodeStatuses, loading: graphLoading, error: graphError } = useConceptMap(activeBook);
  const [selectedNode, setSelectedNode] = useState(null);
  const [reviewDueConcepts, setReviewDueConcepts] = useState(new Set());

  /* ── Deep-link: ?book=<slug> opens directly to that book's graph ── */
  const deepLinkedRef = useRef(false);
  useEffect(() => {
    if (!booksLoaded || deepLinkedRef.current) return;
    const bookParam = searchParams.get("book");
    if (!bookParam) return;
    const match = availableBooks.find((b) => b.slug === bookParam);
    if (match) {
      deepLinkedRef.current = true;
      setSelectedSubject(match.subject || null);
      setSelectedBook(match.slug);
      setViewLevel("graph");
    }
  }, [booksLoaded, availableBooks, searchParams]);

  /* ── Fetch books ── */
  useEffect(() => {
    getAvailableBooks()
      .then((res) => { if (Array.isArray(res.data)) setAvailableBooks(res.data); })
      .catch(() => {})
      .finally(() => setBooksLoaded(true));
  }, []);

  /* ── Graph stats for progress ── */
  const masteredSet = useMemo(() => new Set(masteredConcepts || []), [masteredConcepts]);

  useEffect(() => {
    if (availableBooks.length === 0) return;
    setStatsLoading(true);
    const promises = availableBooks.map(async (book) => {
      if (graphCacheRef.current[book.slug]) return graphCacheRef.current[book.slug];
      try {
        const res = await getGraphFull(book.slug);
        const nodeList = res.data?.nodes || [];
        const entry = { slug: book.slug, nodes: nodeList };
        graphCacheRef.current[book.slug] = entry;
        return entry;
      } catch { return { slug: book.slug, nodes: [] }; }
    });
    Promise.all(promises).then((results) => {
      const stats = {};
      results.forEach(({ slug, nodes: nl }) => {
        const total = nl.length;
        const mastered = nl.filter((n) => masteredSet.has(n.concept_id)).length;
        stats[slug] = { total, mastered, pct: total > 0 ? Math.round((mastered / total) * 100) : 0 };
      });
      setBookGraphStats(stats);
      setStatsLoading(false);
    });
  }, [availableBooks, masteredSet]);

  /* ── Review-due concepts ── */
  useEffect(() => {
    if (!student?.id) return;
    getReviewDue(student.id).then((res) => setReviewDueConcepts(new Set(res.data.map((r) => r.concept_id)))).catch(() => {});
  }, [student?.id]);

  /* ── Derived data ── */
  const bySubject = useMemo(() => {
    const map = {};
    availableBooks.forEach((b) => { const s = b.subject || "other"; (map[s] ||= []).push(b); });
    return map;
  }, [availableBooks]);

  const subjects = useMemo(() => Object.keys(bySubject).sort(), [bySubject]);

  const subjectStats = useMemo(() => {
    const out = {};
    for (const [subj, books] of Object.entries(bySubject)) {
      let total = 0, mastered = 0;
      books.forEach((b) => { const s = bookGraphStats[b.slug]; if (s) { total += s.total; mastered += s.mastered; } });
      out[subj] = { total, mastered, bookCount: books.length, pct: total > 0 ? Math.round((mastered / total) * 100) : 0 };
    }
    return out;
  }, [bySubject, bookGraphStats]);

  /* ── Graph helpers (Level 3) ── */
  const { readyNodes, masteredNodes, lockedNodes } = useMemo(() => {
    const ready = [], mastered = [], locked = [];
    nodes.forEach((n) => {
      const s = nodeStatuses[n.concept_id];
      if (s === "ready") ready.push(n); else if (s === "mastered") mastered.push(n); else locked.push(n);
    });
    return { readyNodes: ready, masteredNodes: mastered, lockedNodes: locked };
  }, [nodes, nodeStatuses]);

  const prerequisiteMap = useMemo(() => {
    const map = {};
    edges.forEach(({ source, target }) => { if (!map[target]) map[target] = []; map[target].push(source); });
    return map;
  }, [edges]);

  const selectedPrereqs = useMemo(() => {
    if (!selectedNode || nodeStatuses[selectedNode] !== "locked") return [];
    return (prerequisiteMap[selectedNode] || []).map((id) => ({
      id, title: nodes.find((n) => n.concept_id === id)?.title || formatConceptTitle(id), status: nodeStatuses[id] || "locked",
    }));
  }, [selectedNode, nodeStatuses, prerequisiteMap, nodes]);

  const blinkNodes = useMemo(() => {
    if (!selectedNode || nodeStatuses[selectedNode] !== "locked") return [];
    return prerequisiteMap[selectedNode] || [];
  }, [selectedNode, nodeStatuses, prerequisiteMap]);

  /* ── Analytics ── */
  const trackedRef = useRef(false);
  useEffect(() => {
    if (!graphLoading && nodes.length > 0 && !trackedRef.current) {
      trackedRef.current = true;
      trackEvent("concept_map_viewed", { ready_count: readyNodes.length, mastered_count: masteredNodes.length, locked_count: lockedNodes.length });
    }
  }, [graphLoading, nodes, readyNodes, masteredNodes, lockedNodes]);

  /* ── Navigation ── */
  const goToSubjects = useCallback(() => {
    directionRef.current = "back";
    setViewLevel("subjects"); setSelectedSubject(null); setSelectedBook(null); setSelectedNode(null);
  }, []);

  const goToBooks = useCallback((subj) => {
    directionRef.current = viewLevel === "subjects" ? "forward" : "back";
    setViewLevel("books"); if (subj) setSelectedSubject(subj); setSelectedBook(null); setSelectedNode(null);
  }, [viewLevel]);

  const goToGraph = useCallback((bookSlug) => {
    directionRef.current = "forward";
    setSelectedBook(bookSlug); setSelectedNode(null); trackedRef.current = false; setViewLevel("graph");
  }, []);

  const handleNodeSelect = (nodeId) => {
    setSelectedNode(nodeId);
    trackEvent("concept_selected", { concept_id: nodeId, status: nodeStatuses[nodeId] });
  };

  const buildLessonUrl = (cid) => `/learn/${encodeURIComponent(cid)}?book_slug=${encodeURIComponent(selectedBook)}`;
  const startLesson = (cid) => { trackEvent("lesson_started", { concept_id: cid }); navigate(buildLessonUrl(cid)); };

  /* ── Breadcrumb ── */
  const subjectLabel = selectedSubject ? t(`subject.${selectedSubject}`, selectedSubject.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())) : "";
  const bookTitle = selectedBook ? (availableBooks.find((b) => b.slug === selectedBook)?.title || selectedBook) : "";

  const breadcrumbItems = useMemo(() => {
    const items = [
      { label: t("nav.dashboard", "Dashboard"), onClick: () => navigate("/dashboard") },
      { label: t("map.explore", "Explore"), onClick: viewLevel !== "subjects" ? goToSubjects : undefined },
    ];
    if (viewLevel === "books" || viewLevel === "graph") items.push({ label: subjectLabel, onClick: viewLevel === "graph" ? () => goToBooks(selectedSubject) : undefined });
    if (viewLevel === "graph") items.push({ label: bookTitle });
    return items;
  }, [viewLevel, subjectLabel, bookTitle, goToSubjects, goToBooks, selectedSubject, navigate, t]);

  /* ── Loading ── */
  if (!booksLoaded) return <CenterMsg icon={<Loader size={32} className="text-[var(--color-primary)] animate-spin" />} text={t("common.loading", "Loading...")} />;
  if (booksLoaded && !availableBooks.length) return <CenterMsg icon={<BookOpen size={48} className="opacity-30" />} text={t("map.noBooksAvailable", "No books available yet")} sub={t("map.noBooksHint", "Ask your administrator to publish a book.")} />;

  return (
    <div style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0, overflow: "hidden" }}>
      {/* ── Shimmer keyframes (injected once) ── */}
      <style>{`@keyframes shimmer{0%{background-position:200% 0}to{background-position:-200% 0}}`}</style>

      {/* ── Back button + Breadcrumb ── */}
      <div style={{
        padding: "14px 28px", borderBottom: "1px solid var(--color-border)",
        background: "var(--color-surface)", flexShrink: 0,
        display: "flex", alignItems: "center", gap: "12px",
      }}>
        <button
          onClick={() => {
            if (viewLevel === "graph") goToBooks(selectedSubject);
            else if (viewLevel === "books") goToSubjects();
            else navigate("/dashboard");
          }}
          style={{
            display: "flex", alignItems: "center", gap: "4px",
            background: "none", border: "none", cursor: "pointer",
            color: "var(--color-text-muted)", fontSize: "13px", fontWeight: 500,
            padding: "4px 8px", borderRadius: "8px",
            transition: "background-color 0.15s", flexShrink: 0,
          }}
        >
          <ArrowLeft size={16} />
        </button>
        <Breadcrumb items={breadcrumbItems} />
      </div>

      {/* ── Animated Content ── */}
      <AnimatePresence mode="wait" custom={directionRef.current}>
        {viewLevel === "subjects" && (
          <motion.div key="subjects" custom={directionRef.current}
            variants={slideVariants} initial="enter" animate="center" exit="exit"
            transition={slideTransition}
            style={{ flex: 1, overflowY: "auto", padding: "28px" }}
          >
            <SubjectGrid subjects={subjects} bySubject={bySubject} subjectStats={subjectStats} statsLoading={statsLoading} onSelect={(subj) => { setSelectedSubject(subj); directionRef.current = "forward"; setViewLevel("books"); }} t={t} />
          </motion.div>
        )}

        {viewLevel === "books" && (
          <motion.div key="books" custom={directionRef.current}
            variants={slideVariants} initial="enter" animate="center" exit="exit"
            transition={slideTransition}
            style={{ flex: 1, overflowY: "auto", padding: "28px" }}
          >
            <BookGrid subject={selectedSubject} books={bySubject[selectedSubject] || []} bookGraphStats={bookGraphStats} statsLoading={statsLoading} subjectStats={subjectStats[selectedSubject]} onSelect={goToGraph} t={t} />
          </motion.div>
        )}

        {viewLevel === "graph" && (
          <motion.div key="graph" custom={directionRef.current}
            variants={slideVariants} initial="enter" animate="center" exit="exit"
            transition={slideTransition}
            style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0, overflow: "hidden" }}
          >
            <GraphView
              loading={graphLoading} error={graphError}
              nodes={nodes} edges={edges} nodeStatuses={nodeStatuses}
              selectedNode={selectedNode}
              selectedNodeData={selectedNode ? nodes.find((n) => n.concept_id === selectedNode) : null}
              readyNodes={readyNodes} masteredNodes={masteredNodes} lockedNodes={lockedNodes}
              blinkNodes={blinkNodes} selectedPrereqs={selectedPrereqs}
              reviewDueConcepts={reviewDueConcepts} bookTitle={bookTitle}
              onNodeSelect={handleNodeSelect} onClearSelection={() => setSelectedNode(null)}
              onStartLesson={startLesson} t={t}
            />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   Level 1 — Subject Grid
   ═══════════════════════════════════════════════════════════════ */

function SubjectGrid({ subjects, bySubject, subjectStats, statsLoading, onSelect, t }) {
  return (
    <div>
      {/* Hero */}
      <div style={{
        borderRadius: "24px", padding: "36px 32px", marginBottom: "32px",
        background: "linear-gradient(145deg, #FFF7ED 0%, var(--color-surface) 50%, #EFF6FF 100%)",
        border: "1px solid var(--color-border)",
        position: "relative", overflow: "hidden",
      }}>
        {/* Decorative glow orbs */}
        <div style={{
          position: "absolute", top: "-40px", right: "-20px", width: "180px", height: "180px",
          borderRadius: "50%", background: "radial-gradient(circle, rgba(249,115,22,0.12) 0%, transparent 70%)",
          pointerEvents: "none",
        }} />
        <div style={{
          position: "absolute", bottom: "-60px", left: "20%", width: "200px", height: "200px",
          borderRadius: "50%", background: "radial-gradient(circle, rgba(59,130,246,0.08) 0%, transparent 70%)",
          pointerEvents: "none",
        }} />

        <div style={{ display: "flex", alignItems: "center", gap: "16px", position: "relative" }}>
          <div style={{
            width: "56px", height: "56px", borderRadius: "16px",
            background: "linear-gradient(135deg, #F97316, #FB923C)",
            display: "flex", alignItems: "center", justifyContent: "center",
            boxShadow: "0 4px 16px rgba(249,115,22,0.3)",
          }}>
            <Library size={26} color="#fff" />
          </div>
          <div>
            <h1 style={{ fontSize: "28px", fontWeight: 800, color: "var(--color-text)", fontFamily: "'Outfit', sans-serif", margin: 0, letterSpacing: "-0.02em" }}>
              {t("map.exploreSubjects", "Explore Your Subjects")}
            </h1>
            <p style={{ fontSize: "14px", color: "var(--color-text-muted)", margin: "4px 0 0" }}>
              {t("map.exploreSubjectsDesc", "Choose a subject to start your learning journey")}
            </p>
          </div>
        </div>
      </div>

      {/* Subject Cards */}
      <motion.div variants={staggerContainer} initial="hidden" animate="show"
        style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))", gap: "20px" }}
      >
        {subjects.map((subj, idx) => {
          const color = SUBJECT_COLORS[idx % SUBJECT_COLORS.length];
          const stats = subjectStats[subj] || {};
          const books = bySubject[subj] || [];
          const SubjIcon = SUBJECT_ICONS[subj] || GraduationCap;
          const pct = statsLoading ? 0 : (stats.pct || 0);

          return (
            <motion.div key={subj} variants={staggerItem}
              onClick={() => onSelect(subj)}
              style={{
                borderRadius: "20px", padding: "0", cursor: "pointer",
                background: "var(--color-surface)", border: "1px solid var(--color-border)",
                position: "relative", overflow: "hidden",
              }}
              whileHover={{ y: -5, boxShadow: `0 16px 40px ${color.glow}, 0 4px 12px rgba(0,0,0,0.06)` }}
              whileTap={{ scale: 0.975 }}
            >
              {/* Top accent gradient band */}
              <div style={{
                height: "6px",
                background: `linear-gradient(90deg, ${color.accent}, ${color.text})`,
              }} />

              <div style={{ padding: "24px 28px 28px" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "20px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "16px", flex: 1, minWidth: 0 }}>
                    <div style={{
                      width: "52px", height: "52px", borderRadius: "14px",
                      display: "flex", alignItems: "center", justifyContent: "center",
                      background: `linear-gradient(135deg, ${color.bg}, ${color.bg}dd)`,
                      color: color.text, boxShadow: `0 2px 8px ${color.glow}`,
                    }}>
                      <SubjIcon size={26} />
                    </div>
                    <div style={{ minWidth: 0 }}>
                      <h3 style={{
                        fontSize: "20px", fontWeight: 700, color: "var(--color-text)",
                        fontFamily: "'Outfit', sans-serif", margin: 0, textTransform: "capitalize",
                        letterSpacing: "-0.01em",
                      }}>
                        {t(`subject.${subj}`, subj.replace(/_/g, " "))}
                      </h3>
                      <p style={{ fontSize: "13px", color: "var(--color-text-muted)", margin: "2px 0 0" }}>
                        {t("map.bookCount", "{{count}} books", { count: books.length })}
                      </p>
                    </div>
                  </div>

                  {/* Circular progress */}
                  <div style={{ position: "relative", display: "flex", alignItems: "center", justifyContent: "center" }}>
                    <ProgressRing pct={pct} size={52} stroke={4} color={color.accent} />
                    <span style={{
                      position: "absolute", fontSize: "13px", fontWeight: 800,
                      color: pct > 0 ? color.text : "var(--color-text-muted)",
                      fontFamily: "'Outfit', sans-serif",
                      transform: "rotate(0deg)", /* counteract SVG rotation */
                    }}>
                      {statsLoading ? "…" : `${pct}%`}
                    </span>
                  </div>
                </div>

                {/* Stats chips */}
                <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                  <StatChip color="#22C55E" value={statsLoading ? "—" : stats.mastered || 0} label={t("map.mastered", "Mastered")} />
                  <StatChip color="var(--color-text-muted)" value={statsLoading ? "—" : stats.total || 0} label={t("map.totalConcepts", "Total")} />
                  <div style={{ marginLeft: "auto", display: "flex", alignItems: "center" }}>
                    <motion.div
                      style={{
                        width: "32px", height: "32px", borderRadius: "50%",
                        display: "flex", alignItems: "center", justifyContent: "center",
                        background: color.bg, color: color.text,
                      }}
                      whileHover={{ x: 3 }}
                    >
                      <ChevronRight size={16} />
                    </motion.div>
                  </div>
                </div>
              </div>
            </motion.div>
          );
        })}
      </motion.div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   Level 2 — Book Grid
   ═══════════════════════════════════════════════════════════════ */

function BookGrid({ subject, books, bookGraphStats, statsLoading, subjectStats, onSelect, t }) {
  const subjectIdx = ["mathematics", "nursing", "physics", "chemistry", "biology", "other"].indexOf(subject);
  const color = SUBJECT_COLORS[(subjectIdx >= 0 ? subjectIdx : 0) % SUBJECT_COLORS.length];
  const SubjIcon = SUBJECT_ICONS[subject] || GraduationCap;

  return (
    <div>
      {/* Subject Header */}
      <div style={{
        borderRadius: "24px", padding: "28px 32px", marginBottom: "24px",
        background: "var(--color-surface)", border: "1px solid var(--color-border)",
        position: "relative", overflow: "hidden",
      }}>
        <div style={{
          position: "absolute", top: 0, left: 0, right: 0, height: "5px",
          background: `linear-gradient(90deg, ${color.accent}, ${color.text})`,
        }} />
        {/* Decorative glow */}
        <div style={{
          position: "absolute", top: "-30px", right: "10%", width: "140px", height: "140px",
          borderRadius: "50%", background: `radial-gradient(circle, ${color.glow} 0%, transparent 70%)`,
          pointerEvents: "none",
        }} />

        <div style={{ display: "flex", alignItems: "center", gap: "16px", position: "relative" }}>
          <div style={{
            width: "52px", height: "52px", borderRadius: "14px",
            display: "flex", alignItems: "center", justifyContent: "center",
            background: `linear-gradient(135deg, ${color.bg}, ${color.bg}dd)`,
            color: color.text, boxShadow: `0 2px 8px ${color.glow}`,
          }}>
            <SubjIcon size={26} />
          </div>
          <div style={{ flex: 1 }}>
            <h2 style={{
              fontSize: "24px", fontWeight: 800, color: "var(--color-text)",
              fontFamily: "'Outfit', sans-serif", margin: 0, textTransform: "capitalize",
              letterSpacing: "-0.02em",
            }}>
              {t(`subject.${subject}`, subject?.replace(/_/g, " "))}
            </h2>
            <p style={{ fontSize: "13px", color: "var(--color-text-muted)", margin: "3px 0 0" }}>
              {t("map.bookCount", "{{count}} books", { count: books.length })}
              {subjectStats && ` · ${subjectStats.mastered}/${subjectStats.total} ${t("map.conceptsMastered", "concepts mastered")}`}
            </p>
          </div>
          {subjectStats && (
            <div style={{ position: "relative", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <ProgressRing pct={subjectStats.pct} size={60} stroke={5} color={color.accent} />
              <span style={{
                position: "absolute", fontSize: "15px", fontWeight: 800,
                color: color.text, fontFamily: "'Outfit', sans-serif",
              }}>
                {subjectStats.pct}%
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Book Cards */}
      <motion.div variants={staggerContainer} initial="hidden" animate="show"
        style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: "16px" }}
      >
        {books.map((book, idx) => {
          const stats = bookGraphStats[book.slug];
          const isProcessing = book.processed === false;
          const bookPct = stats?.pct || 0;

          return (
            <motion.div key={book.slug} variants={staggerItem}
              onClick={() => !isProcessing && onSelect(book.slug)}
              style={{
                borderRadius: "18px", padding: "0",
                background: "var(--color-surface)", border: "1px solid var(--color-border)",
                cursor: isProcessing ? "default" : "pointer",
                opacity: isProcessing ? 0.5 : 1,
                overflow: "hidden", position: "relative",
              }}
              whileHover={isProcessing ? {} : { y: -3, boxShadow: `0 12px 32px ${color.glow}, 0 2px 8px rgba(0,0,0,0.04)` }}
              whileTap={isProcessing ? {} : { scale: 0.98 }}
            >
              {/* Left accent bar */}
              <div style={{
                position: "absolute", top: 0, left: 0, bottom: 0, width: "5px",
                background: `linear-gradient(180deg, ${color.accent}, ${color.text})`,
              }} />

              <div style={{ padding: "22px 24px 22px 28px" }}>
                <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: "14px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "14px", flex: 1, minWidth: 0 }}>
                    {/* Book number badge */}
                    <div style={{
                      width: "40px", height: "40px", borderRadius: "12px",
                      display: "flex", alignItems: "center", justifyContent: "center",
                      background: color.bg, color: color.text, flexShrink: 0,
                      fontWeight: 800, fontSize: "15px", fontFamily: "'Outfit', sans-serif",
                    }}>
                      {idx + 1}
                    </div>
                    <div style={{ minWidth: 0 }}>
                      <h3 style={{
                        fontSize: "15px", fontWeight: 700, color: "var(--color-text)",
                        fontFamily: "'Outfit', sans-serif", margin: 0,
                        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                        letterSpacing: "-0.01em",
                      }}>
                        {book.title || book.slug}
                      </h3>
                      {isProcessing ? (
                        <span style={{
                          display: "inline-block", marginTop: "4px",
                          fontSize: "11px", fontWeight: 700, padding: "2px 8px", borderRadius: "6px",
                          background: "rgba(245,158,11,0.12)", color: "var(--color-warning)",
                          border: "1px solid rgba(245,158,11,0.3)",
                        }}>
                          {t("map.processing", "Processing...")}
                        </span>
                      ) : stats ? (
                        <p style={{ fontSize: "12px", color: "var(--color-text-muted)", margin: "2px 0 0" }}>
                          {stats.total} {t("map.concepts", "concepts")} · {stats.mastered} {t("map.mastered", "mastered")}
                        </p>
                      ) : null}
                    </div>
                  </div>

                  {!isProcessing && (
                    <motion.div
                      style={{
                        width: "32px", height: "32px", borderRadius: "50%",
                        display: "flex", alignItems: "center", justifyContent: "center",
                        background: "var(--color-bg)", color: "var(--color-text-muted)", flexShrink: 0,
                      }}
                      whileHover={{ x: 3, color: color.text }}
                    >
                      <ChevronRight size={16} />
                    </motion.div>
                  )}
                </div>

                {/* Progress bar */}
                {!isProcessing && stats && (
                  <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                    <div style={{ flex: 1 }}>
                      <ProgressBar value={bookPct} size="sm" color={color.bar} />
                    </div>
                    <span style={{ fontSize: "12px", fontWeight: 700, color: bookPct > 0 ? color.text : "var(--color-text-muted)", minWidth: "32px", textAlign: "right" }}>
                      {bookPct}%
                    </span>
                  </div>
                )}

                {!isProcessing && !stats && statsLoading && (
                  <div style={{ display: "flex", gap: "8px", marginTop: "4px" }}>
                    <Shimmer w="100%" h={6} />
                  </div>
                )}
              </div>
            </motion.div>
          );
        })}
      </motion.div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   Level 3 — Graph View
   ═══════════════════════════════════════════════════════════════ */

function GraphView({
  loading, error, nodes, edges, nodeStatuses, selectedNode, selectedNodeData,
  readyNodes, masteredNodes, lockedNodes, blinkNodes, selectedPrereqs,
  reviewDueConcepts, bookTitle, onNodeSelect, onClearSelection, onStartLesson, t,
}) {
  if (loading) return <CenterMsg icon={<Loader size={32} className="text-[var(--color-primary)] animate-spin" />} text={t("map.loadingDashboard", "Loading concept map...")} />;
  if (error === "not_ready") return <CenterMsg icon={<span style={{ fontSize: "48px" }}>📚</span>} text={t("map.bookProcessing", "Textbook content is being prepared")} sub={t("map.bookProcessingDesc", "The extraction pipeline is still running.")} />;
  if (error) return <CenterMsg icon={null} text={t("map.errorDashboard", "Error loading map")} sub={error} danger />;

  return (
    <>
      {/* Stat pills */}
      <div style={{
        display: "flex", alignItems: "center", gap: "10px", padding: "12px 28px",
        borderBottom: "1px solid var(--color-border)", background: "var(--color-surface)",
        flexWrap: "wrap", flexShrink: 0,
      }}>
        <StatPill icon={Trophy} count={masteredNodes.length} label={t("map.mastered", "Mastered")} color="#22C55E" />
        <StatPill icon={Target} count={readyNodes.length} label={t("map.readyToLearn", "Ready")} color="#3B82F6" />
        <StatPill icon={Lock} count={lockedNodes.length} label={t("map.locked", "Locked")} color="#94a3b8" />
        <div style={{ flex: 1 }} />
        <span style={{ fontSize: "12px", fontWeight: 600, color: "var(--color-text-muted)" }}>
          {nodes.length} {t("map.totalConcepts", "total")}
        </span>
      </div>

      {/* Graph */}
      <div style={{ flex: 1, position: "relative", overflow: "hidden", minHeight: 0 }}>
        <ConceptGraph nodes={nodes} edges={edges} nodeStatuses={nodeStatuses}
          selectedNode={selectedNode} onNodeClick={onNodeSelect}
          blinkNodes={blinkNodes} bookTitle={bookTitle}
          onBackgroundClick={onClearSelection}
        />

        {/* Detail Panel */}
        <AnimatePresence>
          {selectedNodeData && (
            <motion.div
              initial={{ opacity: 0, x: 20, scale: 0.95 }}
              animate={{ opacity: 1, x: 0, scale: 1 }}
              exit={{ opacity: 0, x: 20, scale: 0.95 }}
              transition={{ type: "spring", stiffness: 400, damping: 30 }}
              style={{
                position: "absolute", top: "16px", right: "16px", width: "300px", zIndex: 10,
                background: "var(--color-surface)",
                backdropFilter: "blur(12px)", WebkitBackdropFilter: "blur(12px)",
                borderRadius: "16px", border: "1px solid var(--color-border)",
                padding: "22px", boxShadow: "0 12px 40px rgba(0,0,0,0.12), 0 2px 8px rgba(0,0,0,0.06)",
              }}
            >
              <StatusBadge status={nodeStatuses[selectedNode]} />
              <h3 style={{ fontSize: "16px", fontWeight: 700, color: "var(--color-text)", margin: "10px 0 4px", letterSpacing: "-0.01em" }}>
                {selectedNodeData.title || formatConceptTitle(selectedNode)}
              </h3>
              <p style={{ fontSize: "13px", color: "var(--color-text-muted)", marginBottom: "14px" }}>
                {t("map.chapterSection", { chapter: selectedNodeData.chapter, section: selectedNodeData.section })}
              </p>

              {nodeStatuses[selectedNode] === "ready" && (
                <ActionBtn onClick={() => onStartLesson(selectedNode)} bg="var(--color-primary-dark)" hoverBg="var(--color-primary)" icon={BookOpen} label={t("map.startLesson", "Start Lesson")} />
              )}

              {nodeStatuses[selectedNode] === "mastered" && (
                <>
                  <div style={{ display: "flex", justifyContent: "center", marginBottom: "12px" }}>
                    <span style={{ display: "inline-flex", alignItems: "center", gap: "4px", padding: "4px 12px", borderRadius: "9999px", background: "rgba(34,197,94,0.12)", color: "var(--color-success)", fontSize: "12px", fontWeight: 700 }}>
                      <CheckCircle size={14} /> {t("map.mastered", "Mastered")}
                    </span>
                  </div>
                  {reviewDueConcepts.has(selectedNode) && (
                    <div style={{ textAlign: "center", marginBottom: "12px" }}>
                      <span style={{ fontSize: "11px", fontWeight: 700, padding: "3px 8px", borderRadius: "6px", background: "rgba(245,158,11,0.12)", color: "var(--color-warning)", border: "1px solid rgba(245,158,11,0.3)" }}>
                        {t("learning.reviewDueBadge", "Review Due")} {t("learning.reviewDue", "")}
                      </span>
                    </div>
                  )}
                  <ActionBtn onClick={() => onStartLesson(selectedNode)} bg="var(--color-success)" icon={RefreshCw} label={t("map.reviewLesson", "Review Lesson")} />
                </>
              )}

              {nodeStatuses[selectedNode] === "locked" && (
                <div>
                  <div style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "12px", fontWeight: 700, color: "var(--color-primary)", textTransform: "uppercase", marginBottom: "8px", letterSpacing: "0.03em" }}>
                    <AlertTriangle size={14} /> {t("map.prereqNeeded", "Prerequisites needed")}
                  </div>
                  {selectedPrereqs.length > 0 ? (
                    <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                      {selectedPrereqs.map((pr) => (
                        <div key={pr.id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "8px 10px", borderRadius: "10px", border: "1px solid var(--color-border)", background: "var(--color-bg)", fontSize: "12px" }}>
                          <span style={{ fontWeight: 600, color: "var(--color-text)", flex: 1, minWidth: 0, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{pr.title}</span>
                          {pr.status === "mastered" ? <CheckCircle size={14} className="text-emerald-500" style={{ flexShrink: 0, marginLeft: "6px" }} />
                            : pr.status === "ready" ? <span style={{ fontSize: "10px", fontWeight: 700, color: "var(--color-primary)", background: "rgba(99,102,241,0.12)", padding: "2px 6px", borderRadius: "4px", flexShrink: 0, marginLeft: "6px" }}>{t("map.readyToLearn", "Ready")}</span>
                            : <Lock size={12} style={{ color: "#94a3b8", flexShrink: 0, marginLeft: "6px" }} />}
                        </div>
                      ))}
                    </div>
                  ) : <p style={{ fontSize: "12px", color: "var(--color-text-muted)" }}>{t("map.completePrereq", "Complete prerequisites to unlock")}</p>}
                  <p style={{ fontSize: "11px", color: "var(--color-text-muted)", marginTop: "8px", fontStyle: "italic", textAlign: "center" }}>{t("map.prereqBlinking", "Prerequisites are highlighted on the map")}</p>
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </>
  );
}

/* ═══════════════════════════════════════════════════════════════
   Shared sub-components
   ═══════════════════════════════════════════════════════════════ */

function CenterMsg({ icon, text, sub, danger }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", gap: "14px", padding: "32px" }}>
      {icon}
      <p style={{ fontSize: "18px", fontWeight: 700, color: danger ? "var(--color-danger)" : "var(--color-text)", fontFamily: "'Outfit', sans-serif" }}>{text}</p>
      {sub && <p style={{ fontSize: "14px", color: "var(--color-text-muted)", maxWidth: "400px", textAlign: "center", lineHeight: 1.5 }}>{sub}</p>}
    </div>
  );
}

function StatPill({ icon: Icon, count, label, color }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: "5px",
      padding: "5px 12px", borderRadius: "9999px", fontSize: "12px", fontWeight: 700,
      color, background: `${color}14`, border: `1.5px solid ${color}28`,
    }}>
      <Icon size={13} />
      <span>{count}</span>
      <span style={{ fontWeight: 600, opacity: 0.75 }}>{label}</span>
    </div>
  );
}

function StatChip({ color, value, label }) {
  return (
    <div style={{
      display: "inline-flex", alignItems: "center", gap: "6px",
      padding: "4px 10px", borderRadius: "8px",
      background: `color-mix(in srgb, ${color} 8%, transparent)`,
      fontSize: "12px",
    }}>
      <div style={{ width: "7px", height: "7px", borderRadius: "50%", background: color, flexShrink: 0 }} />
      <span style={{ fontWeight: 700, color: "var(--color-text)" }}>{value}</span>
      <span style={{ color: "var(--color-text-muted)" }}>{label}</span>
    </div>
  );
}

function StatusBadge({ status }) {
  const { t } = useTranslation();
  const cfg = {
    mastered: { bg: "rgba(34,197,94,0.12)", color: "var(--color-success)", icon: CheckCircle, label: t("map.mastered", "Mastered") },
    ready: { bg: "rgba(99,102,241,0.12)", color: "var(--color-primary)", icon: Play, label: t("map.readyToLearn", "Ready") },
    locked: { bg: "rgba(148,163,184,0.12)", color: "var(--color-text-muted)", icon: Lock, label: t("map.locked", "Locked") },
  };
  const c = cfg[status] || cfg.locked;
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: "4px", padding: "5px 12px", borderRadius: "9999px", background: c.bg, color: c.color, fontSize: "11px", fontWeight: 700, letterSpacing: "0.02em" }}>
      <c.icon size={12} /> {c.label}
    </span>
  );
}

function ActionBtn({ onClick, bg, icon: Icon, label }) {
  return (
    <motion.button
      onClick={onClick}
      whileHover={{ scale: 1.02, boxShadow: "0 4px 16px rgba(0,0,0,0.12)" }}
      whileTap={{ scale: 0.97 }}
      style={{
        display: "flex", alignItems: "center", justifyContent: "center", gap: "8px",
        width: "100%", padding: "11px", borderRadius: "12px", border: "none",
        background: bg, color: "#fff", fontSize: "14px", fontWeight: 700,
        cursor: "pointer", fontFamily: "'Outfit', sans-serif", letterSpacing: "0.01em",
      }}
    >
      <Icon size={18} /> {label}
    </motion.button>
  );
}
