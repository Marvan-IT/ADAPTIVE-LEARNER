import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { getAdminAnalytics } from "../api/admin";
import { BarChart3, Target } from "lucide-react";

const MODE_COLORS = {
  struggling: "#EF4444",
  normal: "#3B82F6",
  fast: "#22C55E",
};

const cardStyle = {
  borderRadius: "12px",
  border: "1px solid #E2E8F0",
  backgroundColor: "#FFFFFF",
  padding: "20px",
  boxShadow: "0 1px 2px rgba(0,0,0,0.04)",
};

const tableContainer = {
  borderRadius: "12px",
  border: "1px solid #E2E8F0",
  overflow: "hidden",
  backgroundColor: "#FFFFFF",
  boxShadow: "0 1px 2px rgba(0,0,0,0.04)",
};

const thStyle = {
  backgroundColor: "#F8FAFC",
  fontSize: "12px",
  fontWeight: 600,
  textTransform: "uppercase",
  letterSpacing: "0.05em",
  color: "#64748B",
  padding: "12px 16px",
  textAlign: "left",
  whiteSpace: "nowrap",
};

const tdStyle = {
  padding: "12px 16px",
  borderBottom: "1px solid #F1F5F9",
  fontSize: "14px",
  color: "#0F172A",
};

const sectionHeading = {
  fontSize: "18px",
  fontWeight: 700,
  color: "#0F172A",
  fontFamily: "'Outfit', sans-serif",
  marginBottom: "16px",
  margin: 0,
};

function ProgressBar({ value }) {
  let color = "#22C55E";
  if (value < 30) color = "#EF4444";
  else if (value < 60) color = "#F97316";

  let textColor = "#16A34A";
  if (value < 30) textColor = "#EF4444";
  else if (value < 60) textColor = "#F97316";

  return (
    <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
      <div style={{ flex: 1, height: "8px", borderRadius: "9999px", backgroundColor: "#F1F5F9", overflow: "hidden" }}>
        <div
          style={{
            height: "100%",
            borderRadius: "9999px",
            backgroundColor: color,
            width: `${Math.min(value, 100)}%`,
            transition: "width 500ms ease",
          }}
        />
      </div>
      <span style={{ fontSize: "14px", fontWeight: 600, color: textColor, width: "48px", textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
        {value}%
      </span>
    </div>
  );
}

export default function AdminAnalyticsPage() {
  const { t } = useTranslation();

  const [analytics, setAnalytics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    getAdminAnalytics()
      .then((r) => setAnalytics(r.data))
      .catch((e) => setError(e.response?.data?.detail || t("admin.analytics.loadError", "Failed to load analytics")))
      .finally(() => setLoading(false));
  }, []);

  const modeDistribution = analytics?.mode_distribution ?? {};
  const totalStudents = Object.values(modeDistribution).reduce((a, b) => a + b, 0);

  const conceptDifficulty = (analytics?.concept_difficulty ?? []).slice(0, 20);
  const masteryRates = (analytics?.mastery_rates ?? [])
    .slice()
    .sort((a, b) => a.rate - b.rate)
    .slice(0, 20);

  return (
    <div style={{ maxWidth: "1000px", margin: "0 auto" }}>
      {/* Header */}
      <h1 style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", fontFamily: "'Outfit', sans-serif", marginBottom: "24px" }}>
        {t("admin.analytics.title", "Analytics")}
      </h1>

      {/* Loading */}
      {loading && (
        <div style={{ color: "#94A3B8", fontSize: "14px" }}>
          {t("admin.loading", "Loading...")}
        </div>
      )}

      {/* Error */}
      {error && (
        <div style={{
          marginBottom: "24px",
          padding: "12px 16px",
          borderRadius: "12px",
          backgroundColor: "#FEF2F2",
          border: "1px solid #FECACA",
          color: "#DC2626",
          fontSize: "14px",
        }}>
          {error}
        </div>
      )}

      {!loading && !error && analytics && (
        <>
          {/* Student Distribution Cards */}
          <section style={{ marginBottom: "40px" }}>
            <h2 style={{ ...sectionHeading, marginBottom: "16px" }}>
              {t("admin.analytics.studentDistribution", "Student Distribution")}
            </h2>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(250px, 1fr))", gap: "16px" }}>
              {["struggling", "normal", "fast"].map((mode) => {
                const count = modeDistribution[mode] ?? 0;
                const pct = totalStudents > 0 ? Math.round((count / totalStudents) * 100) : 0;
                const modeColor = MODE_COLORS[mode];
                return (
                  <div
                    key={mode}
                    style={{
                      ...cardStyle,
                      borderTop: `4px solid ${modeColor}`,
                    }}
                  >
                    <p style={{ fontSize: "14px", color: "#64748B", fontWeight: 500, textTransform: "capitalize", marginBottom: "4px", marginTop: 0 }}>
                      {t(`admin.analytics.mode.${mode}`, mode.charAt(0).toUpperCase() + mode.slice(1))}
                    </p>
                    <p style={{ fontSize: "36px", fontWeight: 700, color: modeColor, fontFamily: "'Outfit', sans-serif", margin: "0 0 4px 0", lineHeight: 1.1 }}>
                      {count}
                    </p>
                    <p style={{ fontSize: "14px", color: "#94A3B8", margin: 0 }}>
                      {pct}% {t("admin.analytics.ofTotal", "of total")}
                    </p>
                  </div>
                );
              })}
            </div>
          </section>

          {/* Concept Difficulty Table */}
          <section style={{ marginBottom: "40px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "16px" }}>
              <BarChart3 size={18} style={{ color: "#94A3B8" }} />
              <h2 style={sectionHeading}>
                {t("admin.analytics.difficultyTitle", "Concept Difficulty Ranking")}
              </h2>
            </div>
            <div style={tableContainer}>
              {conceptDifficulty.length === 0 ? (
                <p style={{ padding: "24px", color: "#94A3B8", fontSize: "14px", margin: 0 }}>
                  {t("admin.analytics.noData", "No data available.")}
                </p>
              ) : (
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr>
                      <th style={{ ...thStyle, width: "64px" }}>
                        {t("admin.analytics.col.rank", "Rank")}
                      </th>
                      <th style={thStyle}>
                        {t("admin.analytics.col.conceptId", "Concept ID")}
                      </th>
                      <th style={{ ...thStyle, textAlign: "right" }}>
                        {t("admin.analytics.col.avgWrong", "Avg Wrong Attempts")}
                      </th>
                      <th style={{ ...thStyle, textAlign: "right" }}>
                        {t("admin.analytics.col.attempts", "Attempts")}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {conceptDifficulty.map((row, idx) => (
                      <tr key={row.concept_id}>
                        <td style={tdStyle}>
                          <span style={{ color: idx === 0 ? "#F97316" : "#94A3B8", fontWeight: idx === 0 ? 700 : 600, fontSize: "14px" }}>
                            #{idx + 1}
                          </span>
                        </td>
                        <td style={{ ...tdStyle, fontFamily: "monospace" }}>
                          {row.concept_id}
                        </td>
                        <td style={{ ...tdStyle, textAlign: "right", fontWeight: 600, fontVariantNumeric: "tabular-nums", color: "#334155" }}>
                          {typeof row.avg_wrong_attempts === "number"
                            ? row.avg_wrong_attempts.toFixed(2)
                            : row.avg_wrong_attempts}
                        </td>
                        <td style={{ ...tdStyle, textAlign: "right", color: "#64748B", fontVariantNumeric: "tabular-nums" }}>
                          {row.attempts}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </section>

          {/* Mastery Rates Table */}
          <section style={{ marginBottom: "40px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "16px" }}>
              <Target size={18} style={{ color: "#94A3B8" }} />
              <h2 style={sectionHeading}>
                {t("admin.analytics.masteryTitle", "Concept Mastery Rates")}
              </h2>
            </div>
            <div style={tableContainer}>
              {masteryRates.length === 0 ? (
                <p style={{ padding: "24px", color: "#94A3B8", fontSize: "14px", margin: 0 }}>
                  {t("admin.analytics.noData", "No data available.")}
                </p>
              ) : (
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr>
                      <th style={thStyle}>
                        {t("admin.analytics.col.conceptId", "Concept ID")}
                      </th>
                      <th style={{ ...thStyle, textAlign: "right" }}>
                        {t("admin.analytics.col.mastered", "Mastered")}
                      </th>
                      <th style={{ ...thStyle, textAlign: "right" }}>
                        {t("admin.analytics.col.attempted", "Attempted")}
                      </th>
                      <th style={{ ...thStyle, minWidth: "180px" }}>
                        {t("admin.analytics.col.rate", "Rate")}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {masteryRates.map((row) => {
                      const rate = typeof row.rate === "number" ? Math.round(row.rate * 100) : row.rate;
                      return (
                        <tr key={row.concept_id}>
                          <td style={{ ...tdStyle, fontFamily: "monospace" }}>
                            {row.concept_id}
                          </td>
                          <td style={{ ...tdStyle, textAlign: "right", fontVariantNumeric: "tabular-nums", color: "#334155" }}>
                            {row.mastered}
                          </td>
                          <td style={{ ...tdStyle, textAlign: "right", color: "#64748B", fontVariantNumeric: "tabular-nums" }}>
                            {row.attempted}
                          </td>
                          <td style={{ ...tdStyle, padding: "12px 16px" }}>
                            <ProgressBar value={rate} />
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
