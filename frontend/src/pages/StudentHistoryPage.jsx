import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { motion } from 'framer-motion';
import { getCardHistory, getSessions, getSessionCardInteractions } from '../api/students';
import { useStudent } from '../context/StudentContext';

function Sparkline({ points }) {
  const W = 80, H = 30, pad = 3;
  if (!points || points.length < 2) return <span style={{ fontSize: "0.75rem", color: "var(--color-text-muted)" }}>—</span>;
  const maxY = Math.max(...points.map(p => p.y), 1);
  const maxX = Math.max(...points.map(p => p.x), 1);
  const pts = points.map(p =>
    `${pad + (p.x / maxX) * (W - 2 * pad)},${H - pad - (p.y / maxY) * (H - 2 * pad)}`
  ).join(' ');
  return (
    <svg width={W} height={H} style={{ display: "inline-block" }}>
      <polyline points={pts} fill="none" stroke="var(--color-primary)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export default function StudentHistoryPage() {
  const { student } = useStudent();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const [history, setHistory] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expandedSession, setExpandedSession] = useState(null);
  const [sessionCards, setSessionCards] = useState({});

  const toggleExpand = async (sessionId) => {
    if (expandedSession === sessionId) { setExpandedSession(null); return; }
    setExpandedSession(sessionId);
    if (!sessionCards[sessionId]) {
      try {
        const res = await getSessionCardInteractions(sessionId);
        setSessionCards(prev => ({ ...prev, [sessionId]: res.data.interactions }));
      } catch {
        setSessionCards(prev => ({ ...prev, [sessionId]: [] }));
      }
    }
  };

  useEffect(() => {
    if (!student?.id) return;
    Promise.all([
      getCardHistory(student.id),
      getSessions(student.id).catch(() => ({ data: { sessions: [] } })),
    ])
      .then(([histRes, sessRes]) => {
        setHistory(histRes.data);
        setSessions(sessRes.data.sessions ?? []);
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [student?.id]);

  if (loading) return (
    <div style={{
      minHeight: "100vh",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      color: "var(--color-text-muted)",
    }}>
      {t("history.loading", "Loading history...")}
    </div>
  );

  if (error) return (
    <div style={{
      minHeight: "100vh",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      color: "var(--color-danger)",
    }}>
      Error: {error}
    </div>
  );

  const interactions = history?.interactions ?? [];

  // Summary stats
  const totalCards = interactions.length;
  const avgTime = totalCards > 0
    ? (interactions.reduce((s, i) => s + i.time_on_card_sec, 0) / totalCards).toFixed(1)
    : 0;
  const totalWrong = interactions.reduce((s, i) => s + i.wrong_attempts, 0);
  const concepts = [...new Set(interactions.map(i => i.concept_id))];

  // Group by concept for sparklines
  const byConcept = {};
  for (const item of interactions) {
    if (!byConcept[item.concept_id]) byConcept[item.concept_id] = [];
    byConcept[item.concept_id].push(item);
  }

  const summaryStats = [
    { label: t("history.cardsCompleted", "Cards Completed"), value: totalCards },
    { label: t("history.avgTime", "Avg Time/Card"), value: `${avgTime}s` },
    { label: t("history.totalWrong", "Total Wrong Attempts"), value: totalWrong },
    { label: t("history.conceptsStudied", "Concepts Studied"), value: concepts.length },
  ];

  return (
    <div style={{
      minHeight: "100vh",
      backgroundColor: "var(--color-bg)",
      padding: "1.5rem",
    }}>
      <div style={{ maxWidth: "960px", margin: "0 auto" }}>
        {/* Header */}
        <div style={{ borderLeft: "4px solid var(--color-primary)", paddingLeft: "var(--sp-4)", marginBottom: "1.5rem" }}>
          <button
            onClick={() => navigate(-1)}
            style={{ background: "none", border: "none", cursor: "pointer", color: "var(--color-text-muted)", fontFamily: "inherit", fontSize: "0.875rem", fontWeight: 600, padding: 0, marginBottom: "0.35rem", display: "block" }}
          >
            {t("history.back", "← Back")}
          </button>
          <h1 style={{ fontSize: "1.75rem", fontWeight: 800, color: "var(--color-text)", margin: 0, lineHeight: 1.2 }}>
            {t("history.title", "Learning History")}
          </h1>
        </div>

        {/* Summary stats */}
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
          gap: "1rem",
          marginBottom: "1.5rem",
        }}>
          {summaryStats.map((stat, i) => (
            <motion.div key={stat.label}
              initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.08 }}
              style={{ backgroundColor: "var(--color-surface)", border: "1.5px solid var(--color-border)", borderLeft: "3px solid var(--color-primary)", borderRadius: "var(--radius-lg)", padding: "1rem 1.25rem", boxShadow: "var(--shadow-sm)" }}
            >
              <div style={{ fontSize: "1.75rem", fontWeight: 800, color: "var(--color-primary)", lineHeight: 1 }}>{stat.value}</div>
              <div style={{ fontSize: "0.75rem", color: "var(--color-text-muted)", marginTop: "0.3rem", fontWeight: 600 }}>{stat.label}</div>
            </motion.div>
          ))}
        </div>

        {/* Session arc sparklines by concept */}
        {Object.keys(byConcept).length > 0 && (
          <div style={{
            backgroundColor: "var(--color-surface)",
            border: "1.5px solid var(--color-border)",
            borderRadius: "var(--radius-lg)",
            padding: "1rem 1.25rem",
            marginBottom: "1.5rem",
            boxShadow: "var(--shadow-sm)",
          }}>
            <h2 style={{
              fontSize: "0.875rem",
              fontWeight: 700,
              color: "var(--color-text)",
              marginBottom: "0.75rem",
            }}>
              {t("history.sessionArcs", "Session Arcs by Concept")}
            </h2>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "1rem" }}>
              {Object.entries(byConcept).map(([cid, items]) => (
                <div key={cid} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "0.25rem" }}>
                  <Sparkline
                    points={
                      items
                        .slice()
                        .sort((a, b) => a.card_index - b.card_index)
                        .map(i => ({ x: i.card_index, y: i.time_on_card_sec }))
                    }
                  />
                  <span style={{
                    fontSize: "0.625rem",
                    color: "var(--color-text-muted)",
                    maxWidth: "80px",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                    textAlign: "center",
                  }} title={cid}>
                    {cid}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Session Outcomes */}
        {sessions.length > 0 && (
          <div style={{
            backgroundColor: "var(--color-surface)",
            border: "1.5px solid var(--color-border)",
            borderRadius: "var(--radius-lg)",
            overflow: "hidden",
            boxShadow: "var(--shadow-sm)",
            marginBottom: "1.5rem",
          }}>
            <div style={{
              padding: "0.75rem 1.25rem",
              borderBottom: "1.5px solid var(--color-border)",
              backgroundColor: "var(--color-bg)",
            }}>
              <h2 style={{
                fontSize: "0.875rem",
                fontWeight: 700,
                color: "var(--color-text)",
                margin: 0,
              }}>
                {t("history.sessionOutcomes", "Session Outcomes")}
              </h2>
            </div>
            <div style={{ padding: "0.75rem" }}>
              {sessions.map((s, i) => {
                const score = s.check_score ?? null;
                const scoreColor = score === null ? "var(--color-text-muted)" : score >= 60 ? "var(--color-success)" : score >= 40 ? "var(--color-warning)" : "var(--color-danger)";
                const isExpanded = expandedSession === s.id;
                const cards = sessionCards[s.id];
                return (
                  <motion.div key={s.id}
                    initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.04 }}
                    whileHover={{ borderColor: "var(--color-primary)" }}
                    onClick={() => toggleExpand(s.id)}
                    style={{ background: "var(--color-surface)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-lg)", padding: "var(--sp-4)", marginBottom: "var(--sp-3)", cursor: "pointer", transition: "border-color 150ms" }}
                  >
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "0.75rem" }}>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: "0.875rem", fontWeight: 600, color: "var(--color-text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.concept_id}</div>
                        <div style={{ fontSize: "0.72rem", color: "var(--color-text-muted)", marginTop: "2px" }}>
                          {(s.started_at || s.completed_at) ? new Date(s.started_at || s.completed_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—'}
                        </div>
                      </div>
                      {score !== null && (
                        <span style={{ fontSize: "1rem", fontWeight: 800, color: scoreColor }}>{score}%</span>
                      )}
                      <span style={{ fontSize: "0.75rem", color: "var(--color-text-muted)" }}>{isExpanded ? '▲' : '▼'}</span>
                    </div>
                    {isExpanded && cards && cards.length > 0 && (
                      <div style={{ marginTop: "0.75rem", borderTop: "1px solid var(--color-border)", paddingTop: "0.75rem" }}>
                        {cards.map((c, ci) => (
                          <div key={ci} style={{ display: "flex", gap: "1rem", fontSize: "0.78rem", color: "var(--color-text-muted)", padding: "0.25rem 0", borderBottom: ci < cards.length - 1 ? "1px solid var(--color-border)" : "none" }}>
                            <span style={{ color: "var(--color-primary)", fontWeight: 700, minWidth: "40px" }}>#{c.card_index + 1}</span>
                            <span>{c.time_on_card_sec.toFixed(1)}s</span>
                            <span>{c.wrong_attempts} wrong</span>
                            <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.adaptation_applied || '—'}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </motion.div>
                );
              })}
            </div>
          </div>
        )}

        {/* Empty state */}
        {interactions.length === 0 && (
          <div style={{
            textAlign: "center",
            padding: "3rem 1rem",
            color: "var(--color-text-muted)",
          }}>
            <div style={{ fontSize: "3rem", marginBottom: "0.75rem" }}>📚</div>
            <p style={{ fontWeight: 600 }}>
              {t("history.noSessions", "No learning history yet. Complete some cards to see your progress here!")}
            </p>
          </div>
        )}

        {/* Interactions table */}
        {interactions.length > 0 && (
          <div style={{
            backgroundColor: "var(--color-surface)",
            border: "1.5px solid var(--color-border)",
            borderRadius: "var(--radius-lg)",
            overflow: "hidden",
            boxShadow: "var(--shadow-sm)",
          }}>
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", fontSize: "0.875rem", borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{
                    borderBottom: "1.5px solid var(--color-border)",
                    backgroundColor: "var(--color-bg)",
                  }}>
                    {['Concept', 'Card #', 'Time (s)', 'Wrong', 'Hints', 'Idle', 'Adaptation', 'Date'].map(h => (
                      <th
                        key={h}
                        style={{
                          textAlign: "left",
                          padding: "0.6rem 0.75rem",
                          fontSize: "0.75rem",
                          fontWeight: 700,
                          color: "var(--color-text-muted)",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {interactions.map((item, i) => (
                    <tr
                      key={item.id}
                      style={{
                        borderBottom: "1px solid var(--color-border)",
                        backgroundColor: i % 2 === 0 ? "transparent" : "color-mix(in srgb, var(--color-bg) 50%, transparent)",
                      }}
                    >
                      <td style={{
                        padding: "0.5rem 0.75rem",
                        color: "var(--color-text)",
                        maxWidth: "120px",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }} title={item.concept_id}>
                        {item.concept_id}
                      </td>
                      <td style={{ padding: "0.5rem 0.75rem", color: "var(--color-text-muted)" }}>
                        {item.card_index + 1}
                      </td>
                      <td style={{ padding: "0.5rem 0.75rem", color: "var(--color-text-muted)" }}>
                        {item.time_on_card_sec.toFixed(1)}
                      </td>
                      <td style={{ padding: "0.5rem 0.75rem", color: "var(--color-text-muted)" }}>
                        {item.wrong_attempts}
                      </td>
                      <td style={{ padding: "0.5rem 0.75rem", color: "var(--color-text-muted)" }}>
                        {item.hints_used}
                      </td>
                      <td style={{ padding: "0.5rem 0.75rem", color: "var(--color-text-muted)" }}>
                        {item.idle_triggers}
                      </td>
                      <td style={{ padding: "0.5rem 0.75rem", color: "var(--color-text-muted)", fontSize: "0.75rem" }}>
                        {item.adaptation_applied || '—'}
                      </td>
                      <td style={{ padding: "0.5rem 0.75rem", color: "var(--color-text-muted)", fontSize: "0.75rem", whiteSpace: "nowrap" }}>
                        {new Date(item.completed_at).toLocaleDateString('en-US', {
                          month: 'short',
                          day: 'numeric',
                          hour: '2-digit',
                          minute: '2-digit',
                        })}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
