import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Trophy, Medal, Crown } from "lucide-react";
import { motion } from "framer-motion";
import { getLeaderboard, getFeatureFlags } from "../api/students";
import { useStudent } from "../context/StudentContext";
import { Avatar } from "../components/ui";

// ── Shared helpers ────────────────────────────────────────────────

function computeLevel(xp) {
  return Math.floor((xp || 0) / 100) + 1;
}

function formatXP(xp) {
  return (xp || 0).toLocaleString();
}

function RankIcon({ rank }) {
  if (rank === 1) return <Crown size={16} style={{ color: "var(--color-primary)" }} aria-hidden="true" />;
  if (rank === 2) return <Medal size={16} style={{ color: "#6b7280" }} aria-hidden="true" />;
  if (rank === 3) return <Medal size={16} style={{ color: "#c2410c" }} aria-hidden="true" />;
  return null;
}

// ── Podium block for top-3 ────────────────────────────────────────

const PODIUM_CONFIG = {
  1: {
    avatarSize: 80,
    blockH: 112,
    gradientFrom: "#FBBF24",
    gradientTo: "#F59E0B",
    ringColor: "#FBBF24",
    labelColor: "#D97706",
    order: 2,
  },
  2: {
    avatarSize: 64,
    blockH: 80,
    gradientFrom: "#CBD5E1",
    gradientTo: "#94A3B8",
    ringColor: "#CBD5E1",
    labelColor: "#64748B",
    order: 1,
  },
  3: {
    avatarSize: 56,
    blockH: 64,
    gradientFrom: "#FCA37A",
    gradientTo: "#FB923C",
    ringColor: "#FCA37A",
    labelColor: "#EA580C",
    order: 3,
  },
};

function PodiumEntry({ entry, rank, isYou }) {
  const { t } = useTranslation();
  const level = computeLevel(entry.xp);
  const c = PODIUM_CONFIG[rank];

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: rank === 1 ? 0.1 : rank === 2 ? 0.2 : 0.3 }}
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        order: c.order,
        width: 112,
        minWidth: 96,
      }}
    >
      {/* Crown for #1 */}
      {rank === 1 && (
        <Crown size={24} style={{ color: "#F59E0B", marginBottom: 4 }} aria-hidden="true" />
      )}

      {/* Avatar */}
      <div
        style={{
          width: c.avatarSize,
          height: c.avatarSize,
          borderRadius: "50%",
          boxShadow: `0 0 0 4px ${c.ringColor}`,
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          fontWeight: 700,
          color: "#ffffff",
          flexShrink: 0,
          background: "var(--color-primary)",
          marginBottom: 8,
          overflow: "hidden",
        }}
      >
        <Avatar name={entry.display_name} size={rank === 1 ? "lg" : "md"} />
      </div>

      {/* Name + You badge */}
      <span
        style={{
          fontSize: 14,
          fontWeight: 600,
          color: "var(--color-text)",
          textAlign: "center",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
          maxWidth: "100%",
        }}
      >
        {entry.display_name}
      </span>
      {isYou && (
        <span
          style={{
            fontSize: 10,
            fontWeight: 700,
            color: "#ffffff",
            background: "var(--color-primary)",
            borderRadius: 9999,
            paddingLeft: 8,
            paddingRight: 8,
            paddingTop: 2,
            paddingBottom: 2,
            marginTop: 2,
          }}
        >
          {t("leaderboard.you", "You")}
        </span>
      )}

      {/* XP + Level */}
      <span
        style={{
          fontSize: 12,
          fontWeight: 700,
          marginTop: 4,
          color: c.labelColor,
        }}
      >
        <span style={{ color: "#F59E0B" }}>★</span> {formatXP(entry.xp)} XP
      </span>
      <span style={{ fontSize: 10, color: "var(--color-text-muted)" }}>
        {t("leaderboard.levelShort", "Lv.")} {level}
      </span>

      {/* Podium block */}
      <div
        style={{
          width: "100%",
          height: c.blockH,
          background: `linear-gradient(to bottom, ${c.gradientFrom}, ${c.gradientTo})`,
          borderTopLeftRadius: 16,
          borderTopRightRadius: 16,
          marginTop: 8,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <span
          style={{
            color: "#ffffff",
            fontSize: 24,
            fontWeight: 700,
            fontFamily: "'Outfit', sans-serif",
          }}
        >
          {rank}
        </span>
      </div>
    </motion.div>
  );
}

// ── LeaderboardMini — compact sidebar widget ──────────────────────

export function LeaderboardMini() {
  const { t } = useTranslation();
  const { student } = useStudent();

  const [rows, setRows] = useState([]);
  const [yourRank, setYourRank] = useState(null);
  const [disabled, setDisabled] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getFeatureFlags()
      .then((r) => {
        if (r.data?.leaderboard_enabled !== true) {
          setDisabled(true);
          setLoading(false);
          return;
        }
        return getLeaderboard(3).then((res) => {
          setRows(res.data?.entries ?? res.data ?? []);
          setYourRank(res.data?.your_rank ?? null);
        });
      })
      .catch(() => {
        // Silent — mini widget should not surface errors prominently
      })
      .finally(() => setLoading(false));
  }, []);

  if (disabled || loading) return null;
  if (rows.length === 0) return null;

  return (
    <div
      style={{
        border: "1px solid var(--color-border)",
        borderRadius: 12,
        background: "var(--color-surface)",
        paddingLeft: 14,
        paddingRight: 14,
        paddingTop: 12,
        paddingBottom: 12,
      }}
      aria-label={t("leaderboard.miniTitle", "Top Learners")}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          marginBottom: 10,
          fontSize: 13,
          fontWeight: 700,
          color: "var(--color-text)",
        }}
      >
        <Trophy size={14} style={{ color: "var(--color-primary)" }} aria-hidden="true" />
        {t("leaderboard.miniTitle", "Top Learners")}
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {rows.map((entry, idx) => {
          const rank = idx + 1;
          const isCurrentStudent = student?.id && entry.id === student.id;

          let rowBg = "transparent";
          if (isCurrentStudent) rowBg = "rgba(249,115,22,0.08)";
          else if (rank === 1) rowBg = "rgba(251,191,36,0.08)";
          else if (rank === 2) rowBg = "rgba(100,116,139,0.06)";
          else if (rank === 3) rowBg = "rgba(249,115,22,0.05)";

          return (
            <div
              key={entry.id ?? idx}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                paddingLeft: 6,
                paddingRight: 6,
                paddingTop: 4,
                paddingBottom: 4,
                borderRadius: 6,
                fontSize: 12,
                background: rowBg,
              }}
            >
              <span
                style={{
                  width: 16,
                  textAlign: "center",
                  fontWeight: 700,
                  color: "#6b7280",
                }}
              >
                {rank}
              </span>
              <span
                style={{
                  flex: 1,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                  color: "var(--color-text)",
                  fontWeight: isCurrentStudent ? 700 : 400,
                }}
              >
                {entry.display_name}
                {isCurrentStudent && (
                  <span
                    style={{
                      marginInlineStart: 4,
                      fontSize: 10,
                      color: "var(--color-primary)",
                      fontWeight: 700,
                    }}
                  >
                    {t("leaderboard.you", "You")}
                  </span>
                )}
              </span>
              <span
                style={{
                  color: "var(--color-primary)",
                  fontWeight: 600,
                  whiteSpace: "nowrap",
                }}
              >
                {formatXP(entry.xp)} {t("leaderboard.xpUnit", "XP")}
              </span>
            </div>
          );
        })}
      </div>

      {yourRank && !rows.some((e) => student?.id && e.id === student.id) && (
        <div
          style={{
            marginTop: 8,
            paddingTop: 8,
            borderTop: "1px solid var(--color-border)",
            fontSize: 11,
            color: "var(--color-text-muted)",
            textAlign: "center",
          }}
        >
          {t("leaderboard.yourRankShort", "Your rank: #{{rank}}", { rank: yourRank })}
        </div>
      )}
    </div>
  );
}

// ── Tab pills (UI-only) ──────────────────────────────────────────

// ── LeaderboardPage — full ranked display ────────────────────────

export default function LeaderboardPage() {
  const { t } = useTranslation();
  const { student } = useStudent();
  const [rows, setRows] = useState([]);
  const [yourRank, setYourRank] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [disabled, setDisabled] = useState(false);

  useEffect(() => {
    getFeatureFlags()
      .then((r) => {
        if (r.data?.leaderboard_enabled !== true) {
          setDisabled(true);
          setLoading(false);
          return;
        }
        return getLeaderboard(20)
          .then((res) => {
            const entries = res.data?.leaderboard ?? res.data?.entries ?? res.data;
            setRows(Array.isArray(entries) ? entries : []);
            setYourRank(res.data?.your_rank ?? null);
          })
          .catch((e) =>
            setError(e.response?.data?.detail || t("leaderboard.loadError", "Failed to load leaderboard"))
          );
      })
      .catch((e) =>
        setError(e.response?.data?.detail || t("leaderboard.loadError", "Failed to load leaderboard"))
      )
      .finally(() => setLoading(false));
  }, []);

  // ── Loading ──
  if (loading) {
    return (
      <div
        style={{
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
          padding: "80px 0",
        }}
        role="status"
        aria-label={t("common.loading", "Loading...")}
      >
        <div
          style={{
            width: 36,
            height: 36,
            borderRadius: "50%",
            border: "3px solid var(--color-primary)",
            borderTopColor: "transparent",
            animation: "spin 0.7s linear infinite",
          }}
        />
      </div>
    );
  }

  // ── Feature disabled ──
  if (disabled) {
    return (
      <div
        style={{
          paddingTop: 40,
          paddingBottom: 40,
          maxWidth: 640,
          margin: "0 auto",
          textAlign: "center",
        }}
      >
        <Trophy size={48} style={{ color: "#d1d5db", margin: "0 auto 16px auto", display: "block" }} aria-hidden="true" />
        <p style={{ color: "#6b7280", fontSize: 15 }}>
          {t("leaderboard.disabled", "The leaderboard is not enabled yet.")}
        </p>
      </div>
    );
  }

  // ── Error ──
  if (error) {
    return (
      <div style={{ padding: 40 }}>
        <div
          style={{
            paddingLeft: 16,
            paddingRight: 16,
            paddingTop: 12,
            paddingBottom: 12,
            background: "#fef2f2",
            border: "1px solid #fca5a5",
            borderRadius: 8,
            color: "#dc2626",
            fontSize: 14,
          }}
        >
          {error}
        </div>
      </div>
    );
  }

  const top3 = rows.slice(0, 3);
  const rest = rows.slice(3);

  // ── Main render ──
  return (
    <div style={{ flex: 1, overflowY: "auto", padding: 24 }}>
      <div style={{ maxWidth: 760, margin: "0 auto", paddingTop: 8 }}>
        {/* Header */}
        <h1
          style={{
            fontSize: 30,
            fontWeight: 700,
            color: "var(--color-text)",
            textAlign: "center",
            marginBottom: 4,
            fontFamily: "'Outfit', sans-serif",
          }}
        >
          {t("leaderboard.title", "Leaderboard")} 🏆
        </h1>
        <p style={{ color: "#64748B", textAlign: "center", marginTop: 4, fontSize: 15 }}>
          {t("leaderboard.subtitle", "See how you rank against other learners")}
        </p>

        {rows.length === 0 ? (
          <p style={{ color: "#9ca3af", fontSize: 14, textAlign: "center" }}>
            {t("leaderboard.empty", "No data yet. Complete some lessons to appear here!")}
          </p>
        ) : (
          <>
            {/* Podium — top 3 */}
            {top3.length > 0 && (
              <div
                style={{
                  display: "flex",
                  alignItems: "flex-end",
                  justifyContent: "center",
                  gap: 16,
                  marginBottom: 40,
                }}
              >
                {top3.map((entry, idx) => {
                  const rank = idx + 1;
                  const isYou = student?.id && entry.id === student.id;
                  return (
                    <PodiumEntry key={entry.id ?? idx} entry={entry} rank={rank} isYou={isYou} />
                  );
                })}
              </div>
            )}

            {/* Ranks 4+ list */}
            {rest.length > 0 && (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {rest.map((entry, idx) => {
                  const rank = idx + 4;
                  const isCurrentStudent = student?.id && entry.id === student.id;
                  const level = computeLevel(entry.xp);

                  return (
                    <motion.div
                      key={entry.id ?? idx}
                      initial={{ opacity: 0, y: 8 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: idx * 0.03 }}
                      aria-current={isCurrentStudent ? "true" : undefined}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 16,
                        paddingLeft: 20,
                        paddingRight: 20,
                        paddingTop: 12,
                        paddingBottom: 12,
                        borderRadius: 12,
                        transition: "background 150ms ease",
                        background: isCurrentStudent
                          ? "rgba(249,115,22,0.06)"
                          : "var(--color-surface)",
                        border: isCurrentStudent
                          ? "2px solid rgba(249,115,22,0.4)"
                          : "1px solid var(--color-border)",
                      }}
                    >
                      {/* Rank number */}
                      <span
                        style={{
                          width: 32,
                          textAlign: "center",
                          fontWeight: 700,
                          fontSize: 14,
                          color: "var(--color-text-muted)",
                        }}
                      >
                        {rank}
                      </span>

                      {/* Avatar */}
                      <Avatar name={entry.display_name} size="sm" />

                      {/* Name + You badge */}
                      <div
                        style={{
                          flex: 1,
                          minWidth: 0,
                          display: "flex",
                          alignItems: "center",
                          gap: 8,
                        }}
                      >
                        <span
                          style={{
                            fontSize: 14,
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                            color: "var(--color-text)",
                            fontWeight: isCurrentStudent ? 700 : 500,
                          }}
                        >
                          {entry.display_name}
                        </span>
                        {isCurrentStudent && (
                          <span
                            style={{
                              flexShrink: 0,
                              fontSize: 11,
                              fontWeight: 700,
                              color: "#ffffff",
                              background: "var(--color-primary)",
                              borderRadius: 9999,
                              paddingLeft: 8,
                              paddingRight: 8,
                              paddingTop: 2,
                              paddingBottom: 2,
                            }}
                          >
                            {t("leaderboard.you", "You")}
                          </span>
                        )}
                      </div>

                      {/* XP */}
                      <span
                        style={{
                          fontSize: 14,
                          fontWeight: 600,
                          color: "var(--color-primary)",
                          whiteSpace: "nowrap",
                        }}
                      >
                        <span style={{ color: "#F59E0B" }}>★</span> {formatXP(entry.xp)} XP
                      </span>

                      {/* Level */}
                      <span
                        style={{
                          fontSize: 14,
                          color: "var(--color-text-muted)",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {t("leaderboard.levelShort", "Lv.")} {level}
                      </span>

                      {/* Badges */}
                      <span
                        style={{
                          fontSize: 14,
                          color: "var(--color-text-muted)",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {entry.badge_count ?? 0} {t("leaderboard.col.badges", "Badges")}
                      </span>
                    </motion.div>
                  );
                })}
              </div>
            )}
          </>
        )}

        {/* Show current rank below if not in top-20 */}
        {yourRank && !rows.some((e) => student?.id && e.id === student.id) && (
          <div
            style={{
              marginTop: 16,
              paddingLeft: 16,
              paddingRight: 16,
              paddingTop: 10,
              paddingBottom: 10,
              background: "rgba(249,115,22,0.06)",
              border: "1px solid rgba(249,115,22,0.35)",
              borderRadius: 8,
              fontSize: 14,
              color: "#c2410c",
              fontWeight: 500,
              textAlign: "center",
            }}
          >
            {t("leaderboard.yourRank", "Your current rank: #{{rank}}", { rank: yourRank })}
          </div>
        )}
      </div>
    </div>
  );
}
