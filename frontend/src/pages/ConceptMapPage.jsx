import { useState, useMemo, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { trackEvent } from "../utils/analytics";
import { useConceptMap } from "../hooks/useConceptMap";
import { useStudent } from "../context/StudentContext";
import { useTheme } from "../context/ThemeContext";
import ConceptGraph from "../components/conceptmap/ConceptGraph";
import MapLegend from "../components/conceptmap/MapLegend";
import { formatConceptTitle } from "../utils/formatConceptTitle";
import { getReviewDue } from "../api/students";
import { getAvailableBooks } from "../api/concepts";
import {
  Loader, Play, CheckCircle, Lock, BookOpen, Trophy, Target,
  Skull, Rocket, Gamepad2, AlertTriangle, Heart, RefreshCw,
} from "lucide-react";
import { SUGGESTED_INTERESTS } from "../utils/constants";

export default function ConceptMapPage() {
  const { t } = useTranslation();
  const [selectedBook, setSelectedBook] = useState("prealgebra");
  const [availableBooks, setAvailableBooks] = useState([]);
  const { nodes, edges, nodeStatuses, loading, error } = useConceptMap(selectedBook);
  const { student, masteredConcepts } = useStudent();
  const { style: globalStyle } = useTheme();
  const [selectedNode, setSelectedNode] = useState(null);
  const [lessonStyle, setLessonStyle] = useState(globalStyle);
  const [lessonInterests, setLessonInterests] = useState([]);
  const [reviewDueConcepts, setReviewDueConcepts] = useState(new Set());
  const navigate = useNavigate();

  // Fetch available books on mount — non-critical, silent fail
  useEffect(() => {
    getAvailableBooks()
      .then((res) => {
        if (Array.isArray(res.data) && res.data.length > 0) {
          setAvailableBooks(res.data);
        }
      })
      .catch(() => {});
  }, []);

  // Fetch review-due concepts — non-critical, silent fail
  useEffect(() => {
    if (!student?.id) return;
    getReviewDue(student.id)
      .then((res) => {
        setReviewDueConcepts(new Set(res.data.map((r) => r.concept_id)));
      })
      .catch(() => {});
  }, [student?.id]);

  const STYLE_OPTIONS = useMemo(() => [
    { id: "default", icon: BookOpen, label: t("style.default"), color: "#3b82f6" },
    { id: "pirate", icon: Skull, label: t("style.pirate"), color: "#d97706" },
    { id: "astronaut", icon: Rocket, label: t("style.astronaut"), color: "#7c3aed" },
    { id: "gamer", icon: Gamepad2, label: t("style.gamer"), color: "#22c55e" },
  ], [t]);

  const { readyNodes, masteredNodes, lockedNodes } = useMemo(() => {
    const ready = [];
    const mastered = [];
    const locked = [];
    nodes.forEach((n) => {
      const status = nodeStatuses[n.concept_id];
      if (status === "ready") ready.push(n);
      else if (status === "mastered") mastered.push(n);
      else locked.push(n);
    });
    return { readyNodes: ready, masteredNodes: mastered, lockedNodes: locked };
  }, [nodes, nodeStatuses]);

  const prerequisiteMap = useMemo(() => {
    const map = {};
    edges.forEach(({ source, target }) => {
      if (!map[target]) map[target] = [];
      map[target].push(source);
    });
    return map;
  }, [edges]);

  const selectedPrereqs = useMemo(() => {
    if (!selectedNode || nodeStatuses[selectedNode] !== "locked") return [];
    const prereqs = prerequisiteMap[selectedNode] || [];
    return prereqs.map((id) => ({
      id,
      title: nodes.find((n) => n.concept_id === id)?.title || formatConceptTitle(id),
      status: nodeStatuses[id] || "locked",
    }));
  }, [selectedNode, nodeStatuses, prerequisiteMap, nodes]);

  const blinkNodes = useMemo(() => {
    if (!selectedNode || nodeStatuses[selectedNode] !== "locked") return [];
    return prerequisiteMap[selectedNode] || [];
  }, [selectedNode, nodeStatuses, prerequisiteMap]);

  // Track concept map viewed once nodes are loaded
  const trackedRef = useRef(false);
  useEffect(() => {
    if (!loading && nodes.length > 0 && !trackedRef.current) {
      trackedRef.current = true;
      trackEvent("concept_map_viewed", {
        ready_count: readyNodes.length,
        mastered_count: masteredNodes.length,
        locked_count: lockedNodes.length,
      });
    }
  }, [loading, nodes, readyNodes, masteredNodes, lockedNodes]);

  const handleNodeSelect = (nodeId) => {
    setSelectedNode(nodeId);
    setLessonStyle(globalStyle);
    setLessonInterests([]);
    const nodeTitle = nodes.find((n) => n.concept_id === nodeId)?.title || formatConceptTitle(nodeId);
    trackEvent("concept_selected", { concept_id: nodeId, concept_title: nodeTitle, status: nodeStatuses[nodeId] });
  };

  const toggleInterest = (interest) => {
    setLessonInterests((prev) =>
      prev.includes(interest)
        ? prev.filter((i) => i !== interest)
        : [...prev, interest]
    );
  };

  const buildLessonUrl = (conceptId) => {
    const params = new URLSearchParams({ style: lessonStyle });
    if (lessonInterests.length > 0) params.set("interests", lessonInterests.join(","));
    return `/learn/${encodeURIComponent(conceptId)}?${params.toString()}`;
  };

  const startLesson = (conceptId) => {
    const nodeTitle = nodes.find((n) => n.concept_id === conceptId)?.title || formatConceptTitle(conceptId);
    trackEvent("lesson_started", {
      concept_id: conceptId,
      concept_title: nodeTitle,
      style: lessonStyle,
      interests: lessonInterests,
    });
    navigate(buildLessonUrl(conceptId));
  };

  if (loading) {
    return (
      <div style={{
        display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
        height: "calc(100vh - 64px)", gap: "1rem",
      }}>
        <Loader size={32} color="var(--color-primary)" style={{ animation: "spin 1s linear infinite" }} />
        <p style={{ color: "var(--color-text-muted)" }}>{t("map.loadingDashboard")}</p>
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{
        display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
        height: "calc(100vh - 64px)", gap: "1rem",
      }}>
        <p style={{ color: "var(--color-danger)", fontSize: "1.1rem" }}>{t("map.errorDashboard")}</p>
        <p style={{ color: "var(--color-text-muted)", fontSize: "0.9rem" }}>{error}</p>
      </div>
    );
  }

  const selectedNodeData = selectedNode
    ? nodes.find((n) => n.concept_id === selectedNode)
    : null;

  return (
    <div style={{ display: "flex", height: "calc(100vh - 64px)" }}>
      {/* ─── Left Sidebar: Concept List ─── */}
      <div style={{
        width: "340px", minWidth: "340px",
        borderRight: "2px solid var(--color-border)",
        backgroundColor: "var(--color-surface)",
        overflowY: "auto",
        padding: "1.25rem",
      }}>
        {availableBooks.length > 0 && (
          <div style={{ marginBottom: "1rem" }}>
            <label style={{
              display: "block",
              fontSize: "0.75rem",
              fontWeight: 700,
              color: "var(--color-text-muted)",
              textTransform: "uppercase",
              letterSpacing: "0.05em",
              marginBottom: "0.35rem",
            }}>
              {t("map.book", "Book")}
            </label>
            <select
              value={selectedBook}
              onChange={(e) => {
                setSelectedBook(e.target.value);
                setSelectedNode(null);
              }}
              style={{
                width: "100%",
                padding: "0.45rem 0.75rem",
                borderRadius: "8px",
                border: "1.5px solid var(--color-border)",
                backgroundColor: "var(--color-bg)",
                color: "var(--color-text)",
                fontSize: "0.85rem",
                fontFamily: "inherit",
                cursor: "pointer",
                outline: "none",
              }}
            >
              {availableBooks.map((book) => (
                <option key={book.slug || book} value={book.slug || book} disabled={book.processed === false}>
                  {(book.title || book.slug || book)}{book.processed === false ? " (not yet processed)" : ""}
                </option>
              ))}
            </select>
          </div>
        )}

        <div style={{
          display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "0.5rem",
          marginBottom: "1.25rem",
        }}>
          <StatCard icon={Trophy} label={t("map.mastered")} count={masteredNodes.length} color="#22c55e" />
          <StatCard icon={Target} label={t("map.readyToLearn")} count={readyNodes.length} color="#3b82f6" />
          <StatCard icon={Lock} label={t("map.locked")} count={lockedNodes.length} color="#94a3b8" />
        </div>

        {readyNodes.length > 0 && (
          <div style={{ marginBottom: "1.25rem" }}>
            <h3 style={{
              fontSize: "0.85rem", fontWeight: 700, textTransform: "uppercase",
              color: "#3b82f6", letterSpacing: "0.05em", marginBottom: "0.5rem",
              display: "flex", alignItems: "center", gap: "0.4rem",
            }}>
              <Play size={14} /> {t("map.readyToLearn")}
            </h3>
            {readyNodes.map((n) => (
              <ConceptListItem
                key={n.concept_id}
                node={n}
                status="ready"
                selected={selectedNode === n.concept_id}
                onClick={() => handleNodeSelect(n.concept_id)}
                onLearn={() => startLesson(n.concept_id)}
              />
            ))}
          </div>
        )}

        {masteredNodes.length > 0 && (
          <div style={{ marginBottom: "1.25rem" }}>
            <h3 style={{
              fontSize: "0.85rem", fontWeight: 700, textTransform: "uppercase",
              color: "#22c55e", letterSpacing: "0.05em", marginBottom: "0.5rem",
              display: "flex", alignItems: "center", gap: "0.4rem",
            }}>
              <CheckCircle size={14} /> {t("map.mastered")}
            </h3>
            {masteredNodes.map((n) => (
              <ConceptListItem
                key={n.concept_id}
                node={n}
                status="mastered"
                selected={selectedNode === n.concept_id}
                onClick={() => handleNodeSelect(n.concept_id)}
                onLearn={() => startLesson(n.concept_id)}
                reviewDue={reviewDueConcepts.has(n.concept_id)}
              />
            ))}
          </div>
        )}

        {lockedNodes.length > 0 && (
          <div>
            <h3 style={{
              fontSize: "0.85rem", fontWeight: 700, textTransform: "uppercase",
              color: "#94a3b8", letterSpacing: "0.05em", marginBottom: "0.5rem",
              display: "flex", alignItems: "center", gap: "0.4rem",
            }}>
              <Lock size={14} /> {t("map.lockedCount", { count: lockedNodes.length })}
            </h3>
            <p style={{ fontSize: "0.8rem", color: "var(--color-text-muted)" }}>
              {t("map.lockedHint")}
            </p>
          </div>
        )}
      </div>

      {/* ─── Right: Graph View ─── */}
      <div style={{ flex: 1, position: "relative" }}>
        <ConceptGraph
          nodes={nodes}
          edges={edges}
          nodeStatuses={nodeStatuses}
          selectedNode={selectedNode}
          onNodeClick={handleNodeSelect}
          blinkNodes={blinkNodes}
        />

        <MapLegend />

        {selectedNodeData && (
          <div style={{
            position: "absolute", top: "1rem", right: "1rem",
            width: "310px",
            backgroundColor: "var(--color-surface)",
            borderRadius: "14px",
            border: "2px solid var(--color-border)",
            boxShadow: "0 8px 32px rgba(0,0,0,0.1)",
            padding: "1.25rem",
            zIndex: 10,
          }}>
            <StatusBadge status={nodeStatuses[selectedNode]} />
            <h3 style={{
              fontSize: "1.1rem", fontWeight: 700, color: "var(--color-text)",
              margin: "0.5rem 0 0.3rem",
            }}>
              {selectedNodeData.title || formatConceptTitle(selectedNode)}
            </h3>
            <p style={{ fontSize: "0.85rem", color: "var(--color-text-muted)", marginBottom: "0.75rem" }}>
              {t("map.chapterSection", { chapter: selectedNodeData.chapter, section: selectedNodeData.section })}
            </p>

            {nodeStatuses[selectedNode] === "ready" && (
              <>
                <div style={{
                  fontSize: "0.75rem", fontWeight: 700, color: "var(--color-text-muted)",
                  textTransform: "uppercase", letterSpacing: "0.04em",
                  marginBottom: "0.4rem",
                }}>
                  {t("map.chooseStyle")}
                </div>
                <div style={{
                  display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.35rem",
                  marginBottom: "0.75rem",
                }}>
                  {STYLE_OPTIONS.map(({ id, icon: Icon, label, color }) => (
                    <button
                      key={id}
                      onClick={() => setLessonStyle(id)}
                      aria-label={t("aria.styleOption", { style: label })}
                      style={{
                        display: "flex", alignItems: "center", gap: "0.35rem",
                        padding: "0.4rem 0.6rem",
                        borderRadius: "8px",
                        border: lessonStyle === id
                          ? `2px solid ${color}`
                          : "1.5px solid var(--color-border)",
                        backgroundColor: lessonStyle === id ? `${color}15` : "transparent",
                        color: lessonStyle === id ? color : "var(--color-text-muted)",
                        fontSize: "0.8rem", fontWeight: 700,
                        cursor: "pointer", fontFamily: "inherit",
                        transition: "all 0.15s",
                      }}
                    >
                      <Icon size={15} /> {label}
                    </button>
                  ))}
                </div>

                <div style={{
                  fontSize: "0.75rem", fontWeight: 700, color: "var(--color-text-muted)",
                  textTransform: "uppercase", letterSpacing: "0.04em",
                  marginBottom: "0.3rem",
                  display: "flex", alignItems: "center", gap: "0.3rem",
                }}>
                  <Heart size={12} /> {t("map.whatLike")}
                </div>
                <p style={{ fontSize: "0.68rem", color: "var(--color-text-muted)", marginBottom: "0.4rem" }}>
                  {t("map.pickTopics")}
                </p>
                <div style={{
                  display: "flex", flexWrap: "wrap", gap: "0.3rem",
                  marginBottom: "0.75rem",
                }}>
                  {SUGGESTED_INTERESTS.map((interest) => {
                    const selected = lessonInterests.includes(interest);
                    return (
                      <button
                        key={interest}
                        onClick={() => toggleInterest(interest)}
                        aria-label={t("aria.toggleInterest", { interest: t("interest." + interest) })}
                        aria-pressed={selected}
                        style={{
                          padding: "0.25rem 0.55rem",
                          borderRadius: "20px",
                          border: selected ? "1.5px solid var(--color-primary)" : "1.5px solid var(--color-border)",
                          backgroundColor: selected ? "var(--color-primary)" : "transparent",
                          color: selected ? "#fff" : "var(--color-text-muted)",
                          fontSize: "0.72rem", fontWeight: 600,
                          cursor: "pointer", fontFamily: "inherit",
                          transition: "all 0.15s",
                        }}
                      >
                        {t("interest." + interest)}
                      </button>
                    );
                  })}
                </div>

                <button
                  onClick={() => startLesson(selectedNode)}
                  style={{
                    display: "flex", alignItems: "center", justifyContent: "center", gap: "0.5rem",
                    width: "100%", padding: "0.65rem",
                    borderRadius: "10px", border: "none",
                    backgroundColor: "var(--color-primary)", color: "#fff",
                    fontSize: "0.95rem", fontWeight: 700,
                    cursor: "pointer", fontFamily: "inherit",
                  }}
                >
                  <BookOpen size={18} /> {t("map.startLesson")}
                </button>
              </>
            )}

            {nodeStatuses[selectedNode] === "mastered" && (
              <>
                <div style={{
                  display: "flex", alignItems: "center", justifyContent: "center", gap: "0.4rem",
                  padding: "0.4rem 0.8rem", borderRadius: "20px",
                  backgroundColor: "#dcfce7", color: "#16a34a",
                  fontSize: "0.8rem", fontWeight: 700,
                  margin: "0 auto 0.75rem",
                  width: "fit-content",
                }}>
                  <CheckCircle size={14} /> {t("map.mastered")}
                </div>

                {reviewDueConcepts.has(selectedNode) && (
                  <div style={{
                    display: "flex", alignItems: "center", justifyContent: "center",
                    marginBottom: "0.75rem",
                  }}>
                    <span className="ml-2 px-1.5 py-0.5 rounded text-xs bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 border border-amber-300 dark:border-amber-700">
                      {t("learning.reviewDueBadge")} {t("learning.reviewDue")}
                    </span>
                  </div>
                )}

                <div style={{
                  fontSize: "0.75rem", fontWeight: 700, color: "var(--color-text-muted)",
                  textTransform: "uppercase", letterSpacing: "0.04em",
                  marginBottom: "0.4rem",
                }}>
                  {t("map.chooseStyle")}
                </div>
                <div style={{
                  display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.35rem",
                  marginBottom: "0.75rem",
                }}>
                  {STYLE_OPTIONS.map(({ id, icon: Icon, label, color }) => (
                    <button
                      key={id}
                      onClick={() => setLessonStyle(id)}
                      aria-label={t("aria.styleOption", { style: label })}
                      style={{
                        display: "flex", alignItems: "center", gap: "0.35rem",
                        padding: "0.4rem 0.6rem",
                        borderRadius: "8px",
                        border: lessonStyle === id
                          ? `2px solid ${color}`
                          : "1.5px solid var(--color-border)",
                        backgroundColor: lessonStyle === id ? `${color}15` : "transparent",
                        color: lessonStyle === id ? color : "var(--color-text-muted)",
                        fontSize: "0.8rem", fontWeight: 700,
                        cursor: "pointer", fontFamily: "inherit",
                        transition: "all 0.15s",
                      }}
                    >
                      <Icon size={15} /> {label}
                    </button>
                  ))}
                </div>

                <div style={{
                  fontSize: "0.75rem", fontWeight: 700, color: "var(--color-text-muted)",
                  textTransform: "uppercase", letterSpacing: "0.04em",
                  marginBottom: "0.3rem",
                  display: "flex", alignItems: "center", gap: "0.3rem",
                }}>
                  <Heart size={12} /> {t("map.whatLike")}
                </div>
                <p style={{ fontSize: "0.68rem", color: "var(--color-text-muted)", marginBottom: "0.4rem" }}>
                  {t("map.pickTopics")}
                </p>
                <div style={{
                  display: "flex", flexWrap: "wrap", gap: "0.3rem",
                  marginBottom: "0.75rem",
                }}>
                  {SUGGESTED_INTERESTS.map((interest) => {
                    const selected = lessonInterests.includes(interest);
                    return (
                      <button
                        key={interest}
                        onClick={() => toggleInterest(interest)}
                        aria-label={t("aria.toggleInterest", { interest: t("interest." + interest) })}
                        aria-pressed={selected}
                        style={{
                          padding: "0.25rem 0.55rem",
                          borderRadius: "20px",
                          border: selected ? "1.5px solid var(--color-primary)" : "1.5px solid var(--color-border)",
                          backgroundColor: selected ? "var(--color-primary)" : "transparent",
                          color: selected ? "#fff" : "var(--color-text-muted)",
                          fontSize: "0.72rem", fontWeight: 600,
                          cursor: "pointer", fontFamily: "inherit",
                          transition: "all 0.15s",
                        }}
                      >
                        {t("interest." + interest)}
                      </button>
                    );
                  })}
                </div>

                <button
                  onClick={() => startLesson(selectedNode)}
                  style={{
                    display: "flex", alignItems: "center", justifyContent: "center", gap: "0.5rem",
                    width: "100%", padding: "0.65rem",
                    borderRadius: "10px", border: "none",
                    backgroundColor: "#22c55e", color: "#fff",
                    fontSize: "0.95rem", fontWeight: 700,
                    cursor: "pointer", fontFamily: "inherit",
                  }}
                >
                  <RefreshCw size={18} /> {t("map.reviewLesson")}
                </button>
              </>
            )}

            {nodeStatuses[selectedNode] === "locked" && (
              <div>
                <div style={{
                  display: "flex", alignItems: "center", gap: "0.35rem",
                  fontSize: "0.78rem", fontWeight: 700, color: "#f59e0b",
                  textTransform: "uppercase", marginBottom: "0.5rem",
                }}>
                  <AlertTriangle size={14} /> {t("map.prereqNeeded")}
                </div>
                {selectedPrereqs.length > 0 ? (
                  <div style={{ display: "flex", flexDirection: "column", gap: "0.3rem" }}>
                    {selectedPrereqs.map((pr) => (
                      <div
                        key={pr.id}
                        style={{
                          display: "flex", alignItems: "center", justifyContent: "space-between",
                          padding: "0.4rem 0.6rem",
                          borderRadius: "8px",
                          border: "1px solid var(--color-border)",
                          backgroundColor: "var(--color-bg)",
                          fontSize: "0.8rem",
                        }}
                      >
                        <span style={{
                          fontWeight: 600, color: "var(--color-text)",
                          flex: 1, minWidth: 0,
                          whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                        }}>
                          {pr.title}
                        </span>
                        {pr.status === "mastered" ? (
                          <CheckCircle size={15} color="#22c55e" style={{ flexShrink: 0, marginLeft: "0.3rem" }} />
                        ) : pr.status === "ready" ? (
                          <span style={{
                            fontSize: "0.68rem", fontWeight: 700, color: "#3b82f6",
                            backgroundColor: "#dbeafe", padding: "0.1rem 0.4rem",
                            borderRadius: "6px", flexShrink: 0, marginLeft: "0.3rem",
                          }}>
                            {t("map.readyToLearn")}
                          </span>
                        ) : (
                          <Lock size={13} color="#94a3b8" style={{ flexShrink: 0, marginLeft: "0.3rem" }} />
                        )}
                      </div>
                    ))}
                  </div>
                ) : (
                  <p style={{ fontSize: "0.82rem", color: "var(--color-text-muted)" }}>
                    {t("map.completePrereq")}
                  </p>
                )}
                <p style={{
                  fontSize: "0.72rem", color: "var(--color-text-muted)",
                  marginTop: "0.5rem", fontStyle: "italic", textAlign: "center",
                }}>
                  {t("map.prereqBlinking")}
                </p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/* ─── Sub-components ─── */

function StatCard({ icon: Icon, label, count, color }) {
  return (
    <div style={{
      textAlign: "center", padding: "0.6rem 0.3rem",
      borderRadius: "10px", backgroundColor: "var(--color-bg)",
      border: "1px solid var(--color-border)",
    }}>
      <Icon size={18} color={color} style={{ marginBottom: "0.2rem" }} />
      <div style={{ fontSize: "1.3rem", fontWeight: 800, color }}>{count}</div>
      <div style={{ fontSize: "0.7rem", color: "var(--color-text-muted)", fontWeight: 600 }}>{label}</div>
    </div>
  );
}

function ConceptListItem({ node, status, selected, onClick, onLearn, reviewDue }) {
  const { t } = useTranslation();
  const title = node.title || formatConceptTitle(node.concept_id);
  const borderColor = selected ? "var(--color-primary)" : "var(--color-border)";
  const bgColor = selected ? "var(--color-primary-light)" : "transparent";

  return (
    <div
      onClick={onClick}
      style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "0.6rem 0.75rem", marginBottom: "0.4rem",
        borderRadius: "10px", border: `1.5px solid ${borderColor}`,
        backgroundColor: bgColor,
        cursor: "pointer", transition: "all 0.15s",
      }}
    >
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontSize: "0.88rem", fontWeight: 600, color: "var(--color-text)",
          whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
        }}>
          {title}
        </div>
        <div style={{ fontSize: "0.72rem", color: "var(--color-text-muted)", display: "flex", alignItems: "center", gap: "0.3rem" }}>
          Ch. {node.chapter} &middot; {node.section}
          {reviewDue && (
            <span className="px-1.5 py-0.5 rounded text-xs bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 border border-amber-300 dark:border-amber-700">
              {t("learning.reviewDueBadge")} {t("learning.reviewDue")}
            </span>
          )}
        </div>
      </div>

      {status === "ready" && onLearn && (
        <button
          onClick={(e) => { e.stopPropagation(); onLearn(); }}
          style={{
            display: "flex", alignItems: "center", gap: "0.25rem",
            padding: "0.3rem 0.6rem", borderRadius: "8px", border: "none",
            backgroundColor: "var(--color-primary)", color: "#fff",
            fontSize: "0.75rem", fontWeight: 700,
            cursor: "pointer", fontFamily: "inherit", flexShrink: 0,
          }}
        >
          <Play size={12} /> {t("map.startLesson")}
        </button>
      )}

      {status === "mastered" && onLearn && (
        <button
          onClick={(e) => { e.stopPropagation(); onLearn(); }}
          style={{
            display: "flex", alignItems: "center", gap: "0.25rem",
            padding: "0.3rem 0.6rem", borderRadius: "8px", border: "none",
            backgroundColor: "#dcfce7", color: "#16a34a",
            fontSize: "0.75rem", fontWeight: 700,
            cursor: "pointer", fontFamily: "inherit", flexShrink: 0,
          }}
        >
          <RefreshCw size={12} /> {t("map.reviewLesson")}
        </button>
      )}
      {status === "mastered" && !onLearn && (
        <CheckCircle size={18} color="#22c55e" style={{ flexShrink: 0 }} />
      )}
    </div>
  );
}

function StatusBadge({ status }) {
  const { t } = useTranslation();
  const config = {
    mastered: { bg: "#dcfce7", color: "#16a34a", icon: CheckCircle, label: t("map.mastered") },
    ready: { bg: "#dbeafe", color: "#2563eb", icon: Play, label: t("map.readyToLearn") },
    locked: { bg: "#f1f5f9", color: "#64748b", icon: Lock, label: t("map.locked") },
  };
  const c = config[status] || config.locked;
  const Icon = c.icon;

  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: "0.3rem",
      padding: "0.2rem 0.6rem", borderRadius: "20px",
      backgroundColor: c.bg, color: c.color,
      fontSize: "0.75rem", fontWeight: 700,
    }}>
      <Icon size={13} /> {c.label}
    </span>
  );
}
