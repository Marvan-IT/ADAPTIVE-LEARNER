import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Trophy } from "lucide-react";
import { getLeaderboard, getFeatureFlags } from "../../api/students";
import { useStudent } from "../../context/StudentContext";

/**
 * LeaderboardMini — compact sidebar widget showing top 3 learners
 * + current student's rank if they are not in the top 3.
 *
 * Renders null when the leaderboard feature flag is disabled.
 */
export default function LeaderboardMini() {
  const { t } = useTranslation();
  const { student } = useStudent();

  const [rows, setRows] = useState([]);
  const [yourRank, setYourRank] = useState(null);
  const [loading, setLoading] = useState(true);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    getFeatureFlags()
      .then((r) => {
        if (r.data?.leaderboard_enabled !== true) {
          setLoading(false);
          return;
        }
        setVisible(true);
        return getLeaderboard(3).then((res) => {
          setRows(res.data?.entries ?? res.data ?? []);
          setYourRank(res.data?.your_rank ?? null);
        });
      })
      .catch(() => {
        // Silent — mini widget must not disrupt the parent page on failure
      })
      .finally(() => setLoading(false));
  }, []);

  if (loading || !visible || rows.length === 0) return null;

  const currentStudentInTop3 = rows.some(
    (e) => student?.id && e.id === student.id
  );

  return (
    <aside
      style={{
        border: "1px solid #e5e7eb",
        borderRadius: 10,
        background: "#fff",
        padding: "12px 14px",
        fontFamily: "sans-serif",
        minWidth: 180,
      }}
      aria-label={t("leaderboard.miniTitle", "Top Learners")}
    >
      {/* Title row */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          marginBottom: 10,
          fontSize: 13,
          fontWeight: 700,
          color: "#111827",
        }}
      >
        <Trophy size={14} style={{ color: "var(--color-primary)" }} aria-hidden="true" />
        {t("leaderboard.miniTitle", "Top Learners")}
      </div>

      {/* Top 3 rows */}
      <ol
        style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 4 }}
        aria-label={t("leaderboard.miniTitle", "Top Learners")}
      >
        {rows.map((entry, idx) => {
          const rank = idx + 1;
          const isCurrentStudent = student?.id && entry.id === student.id;

          // Subtle gold/silver/bronze background tints for top 3
          const tintBg = rank === 1 ? "#fef9c3" : rank === 2 ? "#f3f4f6" : "#ffedd5";

          return (
            <li
              key={entry.id ?? idx}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "4px 6px",
                borderRadius: 6,
                background: isCurrentStudent ? "#ede9fe" : tintBg,
                fontSize: 12,
              }}
              aria-current={isCurrentStudent ? "true" : undefined}
            >
              <span
                style={{
                  width: 18,
                  textAlign: "center",
                  fontWeight: 700,
                  color: rank === 1 ? "var(--color-primary)" : rank === 2 ? "#6b7280" : "#c2410c",
                  flexShrink: 0,
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
                  color: "#111827",
                  fontWeight: isCurrentStudent ? 700 : 400,
                }}
                title={entry.display_name}
              >
                {entry.display_name}
                {isCurrentStudent && (
                  <span
                    style={{
                      marginLeft: 4,
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
                  fontSize: 11,
                }}
              >
                {(entry.xp || 0).toLocaleString()}
                {" "}
                {t("leaderboard.xpUnit", "XP")}
              </span>
            </li>
          );
        })}
      </ol>

      {/* Current student's rank when outside top 3 */}
      {yourRank && !currentStudentInTop3 && (
        <div
          style={{
            marginTop: 10,
            paddingTop: 8,
            borderTop: "1px solid #e5e7eb",
            fontSize: 11,
            color: "#6b7280",
            textAlign: "center",
          }}
        >
          {t("leaderboard.yourRankShort", "Your rank: #{{rank}}", { rank: yourRank })}
        </div>
      )}
    </aside>
  );
}
