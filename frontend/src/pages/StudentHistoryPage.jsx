import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { motion } from 'framer-motion';
import { Clock, AlertTriangle, BookOpen, Layers } from 'lucide-react';
import { getCardHistory, getSessions, getSessionCardInteractions } from '../api/students';
import { useStudent } from '../context/StudentContext';

// Design tokens
const COLORS = {
  primary: '#F97316',
  text: '#0F172A',
  muted: '#94A3B8',
  border: '#E2E8F0',
  surface: '#FFFFFF',
  bg: '#FAFAFA',
  success: '#22C55E',
  warning: '#F59E0B',
  danger: '#EF4444',
};

const STAT_ICONS = [
  {
    Icon: Layers,
    iconColor: COLORS.primary,
    iconBg: '#FFF7ED',
  },
  {
    Icon: Clock,
    iconColor: '#3B82F6',
    iconBg: '#DBEAFE',
  },
  {
    Icon: AlertTriangle,
    iconColor: '#F59E0B',
    iconBg: '#FEF3C7',
  },
  {
    Icon: BookOpen,
    iconColor: '#22C55E',
    iconBg: '#DCFCE7',
  },
];

function Sparkline({ points }) {
  const W = 80, H = 30, pad = 3;
  if (!points || points.length < 2) {
    return (
      <span style={{ fontSize: '12px', color: COLORS.muted }}>&mdash;</span>
    );
  }
  const maxY = Math.max(...points.map(p => p.y), 1);
  const maxX = Math.max(...points.map(p => p.x), 1);
  const pts = points.map(p =>
    `${pad + (p.x / maxX) * (W - 2 * pad)},${H - pad - (p.y / maxY) * (H - 2 * pad)}`
  ).join(' ');
  return (
    <svg width={W} height={H} style={{ display: 'inline-block' }}>
      <polyline
        points={pts}
        fill="none"
        stroke={COLORS.primary}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function TableRow({ item, isOdd }) {
  const [hovered, setHovered] = useState(false);
  const { i18n } = useTranslation();

  return (
    <tr
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        borderBottom: `1px solid ${COLORS.border}`,
        backgroundColor: hovered
          ? '#F1F5F9'
          : isOdd
          ? '#F8FAFC'
          : COLORS.surface,
        transition: 'background-color 150ms ease',
      }}
    >
      <td
        title={item.concept_id}
        style={{
          padding: '12px',
          color: COLORS.text,
          maxWidth: '120px',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
          fontSize: '14px',
        }}
      >
        {item.concept_id}
      </td>
      <td style={{ padding: '12px', color: COLORS.muted, fontSize: '14px' }}>
        {item.card_index + 1}
      </td>
      <td style={{ padding: '12px', color: COLORS.muted, fontSize: '14px' }}>
        {item.time_on_card_sec.toFixed(1)}
      </td>
      <td style={{ padding: '12px', color: COLORS.muted, fontSize: '14px' }}>
        {item.wrong_attempts}
      </td>
      <td style={{ padding: '12px', color: COLORS.muted, fontSize: '14px' }}>
        {item.hints_used}
      </td>
      <td style={{ padding: '12px', color: COLORS.muted, fontSize: '14px' }}>
        {item.idle_triggers}
      </td>
      <td style={{ padding: '12px', color: COLORS.muted, fontSize: '12px' }}>
        {item.adaptation_applied || '\u2014'}
      </td>
      <td style={{ padding: '12px', color: COLORS.muted, fontSize: '12px', whiteSpace: 'nowrap' }}>
        {new Date(item.completed_at).toLocaleDateString(i18n.language, {
          month: 'short',
          day: 'numeric',
          hour: '2-digit',
          minute: '2-digit',
        })}
      </td>
    </tr>
  );
}

export default function StudentHistoryPage() {
  const { student } = useStudent();
  const { t, i18n } = useTranslation();
  const [history, setHistory] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expandedSession, setExpandedSession] = useState(null);
  const [sessionCards, setSessionCards] = useState({});
  const [hoveredSession, setHoveredSession] = useState(null);

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
      minHeight: '100vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      color: COLORS.muted,
    }}>
      {t("history.loading", "Loading history...")}
    </div>
  );

  if (error) return (
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      color: COLORS.danger,
    }}>
      {t("common.error")}: {error}
    </div>
  );

  const interactions = history?.interactions ?? [];

  const totalCards = interactions.length;
  const avgTime = totalCards > 0
    ? (interactions.reduce((s, i) => s + i.time_on_card_sec, 0) / totalCards).toFixed(1)
    : 0;
  const totalWrong = interactions.reduce((s, i) => s + i.wrong_attempts, 0);
  const concepts = [...new Set(interactions.map(i => i.concept_id))];

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

  const TABLE_HEADERS = [
    t("history.col.concept", "Concept"),
    t("history.col.cardIndex", "Card #"),
    t("history.col.time", "Time (s)"),
    t("history.col.wrong", "Wrong"),
    t("history.col.hints", "Hints"),
    t("history.col.idle", "Idle"),
    t("history.col.adaptation", "Adaptation"),
    t("history.col.date", "Date"),
  ];

  return (
    <div style={{
      flex: 1,
      overflowY: 'auto',
      padding: '24px',
    }}>
      <div>
        {/* Header */}
        <div style={{
          borderInlineStart: `4px solid ${COLORS.primary}`,
          paddingInlineStart: '16px',
          marginBottom: '24px',
        }}>
          <h1 style={{
            fontSize: '1.75rem',
            fontFamily: "'Outfit', sans-serif",
            fontWeight: 700,
            color: COLORS.text,
            margin: 0,
            lineHeight: 1.2,
          }}>
            {t("history.title", "Learning History")}
          </h1>
        </div>

        {/* Summary stats */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
          gap: '16px',
          marginBottom: '24px',
        }}>
          {summaryStats.map((stat, i) => {
            const { Icon, iconColor, iconBg } = STAT_ICONS[i];
            return (
              <motion.div
                key={stat.label}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.08 }}
                style={{
                  borderRadius: '16px',
                  padding: '20px',
                  backgroundColor: COLORS.surface,
                  border: `1px solid ${COLORS.border}`,
                  boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
                }}
              >
                <div style={{
                  width: '36px',
                  height: '36px',
                  borderRadius: '50%',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  marginBottom: '12px',
                  backgroundColor: iconBg,
                  color: iconColor,
                  flexShrink: 0,
                }}>
                  <Icon size={18} aria-hidden="true" />
                </div>
                <div style={{
                  fontSize: '1.75rem',
                  fontFamily: "'Outfit', sans-serif",
                  fontWeight: 700,
                  color: COLORS.primary,
                  lineHeight: 1,
                }}>
                  {stat.value}
                </div>
                <div style={{
                  fontSize: '12px',
                  color: COLORS.muted,
                  marginTop: '4px',
                  fontWeight: 600,
                }}>
                  {stat.label}
                </div>
              </motion.div>
            );
          })}
        </div>

        {/* Session arc sparklines by concept */}
        {Object.keys(byConcept).length > 0 && (
          <div style={{
            backgroundColor: COLORS.surface,
            border: `1.5px solid ${COLORS.border}`,
            borderRadius: '16px',
            padding: '20px',
            marginBottom: '24px',
            boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
          }}>
            <h2 style={{
              fontSize: '14px',
              fontFamily: "'Outfit', sans-serif",
              fontWeight: 700,
              color: COLORS.text,
              marginBottom: '12px',
              margin: '0 0 12px 0',
            }}>
              {t("history.sessionArcs", "Session Arcs by Concept")}
            </h2>
            <div style={{
              display: 'flex',
              flexWrap: 'wrap',
              gap: '16px',
            }}>
              {Object.entries(byConcept).map(([cid, items]) => (
                <div key={cid} style={{
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  gap: '4px',
                }}>
                  <Sparkline
                    points={
                      items
                        .slice()
                        .sort((a, b) => a.card_index - b.card_index)
                        .map(i => ({ x: i.card_index, y: i.time_on_card_sec }))
                    }
                  />
                  <span
                    title={cid}
                    style={{
                      fontSize: '10px',
                      color: COLORS.muted,
                      maxWidth: '80px',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                      textAlign: 'center',
                    }}
                  >
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
            backgroundColor: COLORS.surface,
            border: `1.5px solid ${COLORS.border}`,
            borderRadius: '16px',
            overflow: 'hidden',
            boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
            marginBottom: '24px',
          }}>
            <div style={{
              padding: '12px 20px',
              borderBottom: `1.5px solid ${COLORS.border}`,
              backgroundColor: COLORS.bg,
            }}>
              <h2 style={{
                fontSize: '14px',
                fontFamily: "'Outfit', sans-serif",
                fontWeight: 700,
                color: COLORS.text,
                margin: 0,
              }}>
                {t("history.sessionOutcomes", "Session Outcomes")}
              </h2>
            </div>
            <div style={{ padding: '12px' }}>
              {sessions.map((s, i) => {
                const score = s.check_score ?? null;
                const scoreColor = score === null
                  ? COLORS.muted
                  : score >= 60
                    ? COLORS.success
                    : score >= 40
                      ? COLORS.warning
                      : COLORS.danger;
                const isExpanded = expandedSession === s.id;
                const isHovered = hoveredSession === s.id;
                const cards = sessionCards[s.id];
                return (
                  <motion.div
                    key={s.id}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.04 }}
                    onClick={() => toggleExpand(s.id)}
                    onMouseEnter={() => setHoveredSession(s.id)}
                    onMouseLeave={() => setHoveredSession(null)}
                    style={{
                      borderRadius: '12px',
                      padding: '16px',
                      marginBottom: '12px',
                      cursor: 'pointer',
                      border: `1px solid ${isHovered ? COLORS.primary : COLORS.border}`,
                      backgroundColor: isHovered ? '#FFF7ED' : COLORS.surface,
                      transition: 'background-color 150ms ease, border-color 150ms ease',
                    }}
                  >
                    <div style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      gap: '12px',
                    }}>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{
                          fontSize: '14px',
                          fontWeight: 600,
                          color: COLORS.text,
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}>
                          {s.concept_id}
                        </div>
                        <div style={{
                          fontSize: '11.5px',
                          color: COLORS.muted,
                          marginTop: '2px',
                        }}>
                          {(s.started_at || s.completed_at)
                            ? new Date(s.started_at || s.completed_at).toLocaleDateString(i18n.language, {
                                month: 'short',
                                day: 'numeric',
                                hour: '2-digit',
                                minute: '2-digit',
                              })
                            : '\u2014'}
                        </div>
                      </div>
                      {score !== null && (
                        <span style={{
                          fontSize: '16px',
                          fontFamily: "'Outfit', sans-serif",
                          fontWeight: 700,
                          color: scoreColor,
                        }}>
                          {score}%
                        </span>
                      )}
                      <span style={{ fontSize: '12px', color: COLORS.muted }}>
                        {isExpanded ? '\u25B2' : '\u25BC'}
                      </span>
                    </div>
                    {isExpanded && cards && cards.length > 0 && (
                      <div style={{
                        marginTop: '12px',
                        borderTop: `1px solid ${COLORS.border}`,
                        paddingTop: '12px',
                      }}>
                        {cards.map((c, ci) => (
                          <div
                            key={ci}
                            style={{
                              display: 'flex',
                              gap: '16px',
                              fontSize: '12.5px',
                              color: COLORS.muted,
                              padding: '4px 0',
                              borderBottom: ci < cards.length - 1 ? `1px solid ${COLORS.border}` : 'none',
                            }}
                          >
                            <span style={{
                              color: COLORS.primary,
                              fontWeight: 700,
                              minWidth: '40px',
                            }}>
                              #{c.card_index + 1}
                            </span>
                            <span>{c.time_on_card_sec.toFixed(1)}s</span>
                            <span>{c.wrong_attempts} {t("history.col.wrong", "Wrong")}</span>
                            <span style={{
                              flex: 1,
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                              whiteSpace: 'nowrap',
                            }}>
                              {c.adaptation_applied || '\u2014'}
                            </span>
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
        {interactions.length === 0 && sessions.length === 0 && (
          <div style={{
            textAlign: 'center',
            padding: '48px 16px',
            color: COLORS.muted,
          }}>
            <div style={{ fontSize: '48px', marginBottom: '12px' }}>📚</div>
            <p style={{ fontWeight: 600, margin: 0 }}>
              {t("history.empty", "No learning history yet. Start a lesson to see your progress here!")}
            </p>
          </div>
        )}

        {/* Interactions table */}
        {interactions.length > 0 && (
          <div style={{
            backgroundColor: COLORS.surface,
            border: `1.5px solid ${COLORS.border}`,
            borderRadius: '16px',
            overflow: 'hidden',
            boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
          }}>
            <div style={{ overflowX: 'auto' }}>
              <table style={{
                width: '100%',
                fontSize: '14px',
                borderCollapse: 'collapse',
              }}>
                <thead>
                  <tr style={{
                    borderBottom: `1.5px solid ${COLORS.border}`,
                    backgroundColor: '#F8FAFC',
                  }}>
                    {TABLE_HEADERS.map(h => (
                      <th
                        key={h}
                        style={{
                          textAlign: 'start',
                          padding: '12px',
                          fontSize: '11px',
                          textTransform: 'uppercase',
                          fontWeight: 700,
                          color: COLORS.muted,
                          whiteSpace: 'nowrap',
                          letterSpacing: '0.06em',
                          backgroundColor: '#F8FAFC',
                        }}
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {interactions.map((item, i) => (
                    <TableRow
                      key={item.id}
                      item={item}
                      isOdd={i % 2 !== 0}
                    />
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
