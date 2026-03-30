import { useState, useEffect, Fragment } from 'react';
import { useNavigate } from 'react-router-dom';
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
      Loading history...
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
    { label: 'Cards Completed', value: totalCards },
    { label: 'Avg Time/Card', value: `${avgTime}s` },
    { label: 'Total Wrong Attempts', value: totalWrong },
    { label: 'Concepts Studied', value: concepts.length },
  ];

  return (
    <div style={{
      minHeight: "100vh",
      backgroundColor: "var(--color-bg)",
      padding: "1.5rem",
    }}>
      <div style={{ maxWidth: "960px", margin: "0 auto" }}>
        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", gap: "1rem", marginBottom: "1.5rem" }}>
          <button
            onClick={() => navigate(-1)}
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              color: "var(--color-text-muted)",
              fontFamily: "inherit",
              fontSize: "0.95rem",
              fontWeight: 600,
              padding: "0.25rem",
              transition: "color var(--motion-fast)",
            }}
            onMouseEnter={(e) => (e.currentTarget.style.color = "var(--color-text)")}
            onMouseLeave={(e) => (e.currentTarget.style.color = "var(--color-text-muted)")}
          >
            ← Back
          </button>
          <h1 style={{
            fontSize: "1.5rem",
            fontWeight: 800,
            color: "var(--color-text)",
            margin: 0,
          }}>
            Learning History
          </h1>
        </div>

        {/* Summary stats */}
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
          gap: "1rem",
          marginBottom: "1.5rem",
        }}>
          {summaryStats.map(stat => (
            <div
              key={stat.label}
              style={{
                backgroundColor: "var(--color-surface)",
                border: "1.5px solid var(--color-border)",
                borderRadius: "var(--radius-lg)",
                padding: "1rem 1.25rem",
                boxShadow: "var(--shadow-sm)",
              }}
            >
              <div style={{
                fontSize: "1.75rem",
                fontWeight: 800,
                color: "var(--color-primary)",
                lineHeight: 1,
              }}>
                {stat.value}
              </div>
              <div style={{
                fontSize: "0.75rem",
                color: "var(--color-text-muted)",
                marginTop: "0.3rem",
                fontWeight: 600,
              }}>
                {stat.label}
              </div>
            </div>
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
              Session Arcs by Concept
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
                Session Outcomes
              </h2>
            </div>
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", fontSize: "0.875rem", borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ borderBottom: "1px solid var(--color-border)" }}>
                    {['Concept', 'Score', 'Status', 'Date', ''].map(h => (
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
                  {sessions.map((s, i) => {
                    const score = s.check_score ?? null;
                    const scoreColor = score === null
                      ? "var(--color-text-muted)"
                      : score >= 60 ? "#16a34a" : score >= 40 ? "#d97706" : "#dc2626";
                    const scoreBg = score === null
                      ? "color-mix(in srgb, var(--color-border) 40%, transparent)"
                      : score >= 60
                        ? "color-mix(in srgb, #16a34a 12%, transparent)"
                        : score >= 40
                          ? "color-mix(in srgb, #d97706 12%, transparent)"
                          : "color-mix(in srgb, #dc2626 12%, transparent)";

                    const statusBadge = s.phase === "COMPLETED"
                      ? s.mastered
                        ? <span style={{ color: "#16a34a", fontWeight: 700 }}>✓ Mastered</span>
                        : <span style={{ color: "#dc2626", fontWeight: 700 }}>✗ Not Mastered</span>
                      : s.phase === "CHECKING"
                        ? <span style={{ color: "var(--color-primary)", fontWeight: 600 }}>💬 In Chat</span>
                        : s.phase === "COMPLETED"
                          ? <span style={{ color: "#d97706", fontWeight: 600 }}>📚 Cards Done</span>
                          : <span style={{ color: "var(--color-text-muted)", fontWeight: 600 }}>🔄 In Progress</span>;

                    const isExpanded = expandedSession === s.id;
                    const cards = sessionCards[s.id];
                    const rowBg = i % 2 === 0 ? "transparent" : "color-mix(in srgb, var(--color-bg) 50%, transparent)";

                    return (
                      <Fragment key={s.id}>
                        <tr style={{ borderBottom: isExpanded ? "none" : "1px solid var(--color-border)", backgroundColor: rowBg }}>
                          <td
                            style={{ padding: "0.5rem 0.75rem", color: "var(--color-text)", maxWidth: "160px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontSize: "0.8rem" }}
                            title={s.concept_id}
                          >
                            {s.concept_id}
                          </td>
                          <td style={{ padding: "0.5rem 0.75rem" }}>
                            <span style={{ display: "inline-block", padding: "0.15rem 0.5rem", borderRadius: "999px", fontSize: "0.75rem", fontWeight: 700, color: scoreColor, backgroundColor: scoreBg }}>
                              {score !== null ? `${score}%` : '—'}
                            </span>
                          </td>
                          <td style={{ padding: "0.5rem 0.75rem", fontSize: "0.8rem" }}>
                            {statusBadge}
                          </td>
                          <td style={{ padding: "0.5rem 0.75rem", color: "var(--color-text-muted)", fontSize: "0.75rem", whiteSpace: "nowrap" }}>
                            {(s.started_at || s.completed_at)
                              ? new Date(s.started_at || s.completed_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
                              : '—'}
                          </td>
                          <td style={{ padding: "0.5rem 0.75rem", textAlign: "right" }}>
                            <button
                              onClick={() => toggleExpand(s.id)}
                              title={isExpanded ? "Collapse card details" : "Expand card details"}
                              style={{ background: "none", border: "none", cursor: "pointer", fontSize: "0.85rem", color: "var(--color-text-muted)", padding: "0.1rem 0.3rem" }}
                            >
                              {isExpanded ? '▲' : '▼'}
                            </button>
                          </td>
                        </tr>
                        {isExpanded && (
                          <tr style={{ borderBottom: "1px solid var(--color-border)", backgroundColor: rowBg }}>
                            <td colSpan={5} style={{ padding: "0 0.75rem 0.75rem 1.5rem" }}>
                              {!cards ? (
                                <span style={{ fontSize: "0.8rem", color: "var(--color-text-muted)" }}>Loading…</span>
                              ) : cards.length === 0 ? (
                                <span style={{ fontSize: "0.8rem", color: "var(--color-text-muted)" }}>No card interactions saved for this session.</span>
                              ) : (
                                <table style={{ width: "100%", fontSize: "0.78rem", borderCollapse: "collapse", marginTop: "0.25rem" }}>
                                  <thead>
                                    <tr style={{ borderBottom: "1px solid var(--color-border)" }}>
                                      {['Card #', 'Time (s)', 'Wrong', 'Hints', 'Idle', 'Adaptation'].map(h => (
                                        <th key={h} style={{ textAlign: "left", padding: "0.3rem 0.5rem", fontWeight: 700, color: "var(--color-text-muted)", whiteSpace: "nowrap" }}>{h}</th>
                                      ))}
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {cards.map((c, ci) => (
                                      <tr key={ci} style={{ borderBottom: ci < cards.length - 1 ? "1px solid var(--color-border)" : "none" }}>
                                        <td style={{ padding: "0.3rem 0.5rem", color: "var(--color-primary)", fontWeight: 700 }}>{c.card_index + 1}</td>
                                        <td style={{ padding: "0.3rem 0.5rem" }}>{c.time_on_card_sec.toFixed(1)}</td>
                                        <td style={{ padding: "0.3rem 0.5rem" }}>{c.wrong_attempts}</td>
                                        <td style={{ padding: "0.3rem 0.5rem" }}>{c.hints_used}</td>
                                        <td style={{ padding: "0.3rem 0.5rem" }}>{c.idle_triggers}</td>
                                        <td style={{ padding: "0.3rem 0.5rem", color: "var(--color-text-muted)" }}>{c.adaptation_applied || '—'}</td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              )}
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
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
              No learning history yet. Complete some cards to see your progress here!
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
