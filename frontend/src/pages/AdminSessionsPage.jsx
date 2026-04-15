import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { getAdminSessions } from "../api/admin";

const LIMIT = 50;

const PHASES = ["ALL", "PRESENTING", "CARDS", "CARDS_DONE", "CHECKING", "REMEDIATING", "RECHECKING", "COMPLETED", "SELECTING_CHUNK"];

const PHASE_COLORS = {
  PRESENTING: { color: "#F97316", fontWeight: 600 },
  CARDS: { color: "#3B82F6", fontWeight: 600 },
  CARDS_DONE: { color: "#22C55E", fontWeight: 600 },
  CHECKING: { color: "#A855F7", fontWeight: 600 },
  REMEDIATING: { color: "#EA580C", fontWeight: 600 },
  RECHECKING: { color: "#EC4899", fontWeight: 600 },
  COMPLETED: { color: "#16A34A", fontWeight: 600 },
  SELECTING_CHUNK: { color: "#06B6D4", fontWeight: 600 },
  SOCRATIC: { color: "#A855F7", fontWeight: 600 },
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

const tableContainer = {
  overflowX: "auto",
  backgroundColor: "#FFFFFF",
  borderTop: "1px solid #E2E8F0",
};

const selectStyle = {
  borderRadius: "8px",
  border: "1px solid #E2E8F0",
  height: "40px",
  padding: "0 12px",
  fontSize: "14px",
  color: "#0F172A",
  backgroundColor: "#FFFFFF",
  outline: "none",
  cursor: "pointer",
};

const inputStyle = {
  borderRadius: "8px",
  border: "1px solid #E2E8F0",
  height: "40px",
  padding: "0 12px",
  fontSize: "14px",
  color: "#0F172A",
  backgroundColor: "#FFFFFF",
  outline: "none",
  minWidth: "180px",
};

const linkStyle = {
  color: "#F97316",
  textDecoration: "none",
  fontWeight: 500,
  background: "none",
  border: "none",
  cursor: "pointer",
  padding: 0,
  fontSize: "14px",
};

const pillBtnStyle = {
  padding: "8px 20px",
  borderRadius: "9999px",
  border: "1px solid #E2E8F0",
  backgroundColor: "#FFFFFF",
  fontSize: "14px",
  fontWeight: 500,
  color: "#0F172A",
  cursor: "pointer",
  transition: "background-color 150ms ease",
};

const pillBtnDisabled = {
  ...pillBtnStyle,
  opacity: 0.5,
  cursor: "not-allowed",
};

function PhaseBadge({ phase }) {
  const style = PHASE_COLORS[phase] || { color: "#64748B", fontWeight: 600 };
  return (
    <span style={{ ...style, fontSize: "13px", whiteSpace: "nowrap" }}>
      {phase}
    </span>
  );
}

export default function AdminSessionsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const [sessions, setSessions] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [phaseFilter, setPhaseFilter] = useState("ALL");
  const [bookFilter, setBookFilter] = useState("");
  const [offset, setOffset] = useState(0);

  const load = (phase, book, off) => {
    setLoading(true);
    setError(null);
    const params = { limit: LIMIT, offset: off };
    if (phase !== "ALL") params.phase = phase;
    if (book.trim()) params.book_slug = book.trim();
    getAdminSessions(params)
      .then((r) => {
        const data = r.data;
        setSessions(data.items ?? (Array.isArray(data) ? data : []));
        setTotal(data.total ?? (Array.isArray(data) ? data.length : 0));
      })
      .catch((e) => setError(e.response?.data?.detail || t("admin.loadError", "Failed to load sessions")))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load(phaseFilter, bookFilter, offset);
  }, [phaseFilter, bookFilter, offset]);

  const handlePhaseChange = (e) => {
    setOffset(0);
    setPhaseFilter(e.target.value);
  };

  const handleBookChange = (e) => {
    setOffset(0);
    setBookFilter(e.target.value);
  };

  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + LIMIT, total);

  return (
    <div style={{ margin: "0 auto" }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "20px" }}>
        <h1 style={{ fontSize: "26px", fontWeight: 700, color: "#0F172A", fontFamily: "'Outfit', sans-serif", margin: 0 }}>
          {t("admin.sessionMonitoring", "Sessions")}
        </h1>
        {total > 0 && (
          <span style={{ fontSize: "14px", color: "#94A3B8" }}>
            {t("admin.totalSessions", "{{count}} sessions", { count: total })}
          </span>
        )}
      </div>

      {/* Filter bar */}
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "16px", marginBottom: "20px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <label style={{ fontSize: "14px", fontWeight: 500, color: "#64748B" }}>
            {t("admin.phase", "Phase")}
          </label>
          <select
            value={phaseFilter}
            onChange={handlePhaseChange}
            style={selectStyle}
          >
            {PHASES.map((p) => (
              <option key={p} value={p}>
                {p === "ALL" ? t("admin.filterAll", "All") : p}
              </option>
            ))}
          </select>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <label style={{ fontSize: "14px", fontWeight: 500, color: "#64748B" }}>
            {t("admin.book", "Book")}
          </label>
          <input
            value={bookFilter}
            onChange={handleBookChange}
            placeholder={t("admin.bookSlugPlaceholder", "e.g. prealgebra")}
            style={inputStyle}
          />
        </div>
      </div>

      {/* Error */}
      {error && (
        <div style={{
          marginBottom: "16px",
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

      {/* Loading */}
      {loading && (
        <div style={{ padding: "40px 0", textAlign: "center", color: "#94A3B8", fontSize: "14px" }}>
          {t("admin.loading", "Loading...")}
        </div>
      )}

      {/* Empty */}
      {!loading && !error && sessions.length === 0 && (
        <div style={{ padding: "64px 0", textAlign: "center", color: "#94A3B8" }}>
          <p style={{ fontSize: "16px", margin: 0 }}>{t("admin.noSessions", "No sessions found.")}</p>
        </div>
      )}

      {/* Table */}
      {!loading && sessions.length > 0 && (
        <div style={tableContainer}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={thStyle}>{t("admin.studentName", "Student")}</th>
                <th style={thStyle}>{t("admin.concept", "Concept")}</th>
                <th style={thStyle}>{t("admin.book", "Book")}</th>
                <th style={thStyle}>{t("admin.phase", "Phase")}</th>
                <th style={thStyle}>{t("admin.started", "Started")}</th>
                <th style={thStyle}>{t("admin.completed", "Completed")}</th>
                <th style={thStyle}>{t("admin.score", "Score")}</th>
                <th style={thStyle}>{t("admin.mastered", "Mastered")}</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((s) => (
                <tr
                  key={s.id}
                  style={{ transition: "background-color 0.15s" }}
                  onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = "#FFF7ED"; }}
                  onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = ""; }}
                >
                  <td style={tdStyle}>
                    {s.student_id ? (
                      <button
                        onClick={() => navigate(`/admin/students/${s.student_id}`)}
                        style={linkStyle}
                      >
                        {s.student_name || s.student_id}
                      </button>
                    ) : (
                      <span style={{ color: "#94A3B8" }}>&mdash;</span>
                    )}
                  </td>
                  <td style={{ ...tdStyle, maxWidth: "180px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={s.concept_id}>
                    {s.concept_id || "\u2014"}
                  </td>
                  <td style={{ ...tdStyle, color: "#64748B" }}>
                    {s.book_slug || "\u2014"}
                  </td>
                  <td style={tdStyle}>
                    <PhaseBadge phase={s.phase} />
                  </td>
                  <td style={{ ...tdStyle, color: "#64748B", whiteSpace: "nowrap" }}>
                    {s.created_at ? new Date(s.created_at).toLocaleDateString() : "\u2014"}
                  </td>
                  <td style={{ ...tdStyle, color: "#64748B", whiteSpace: "nowrap" }}>
                    {s.completed_at ? new Date(s.completed_at).toLocaleDateString() : "\u2014"}
                  </td>
                  <td style={tdStyle}>
                    {s.best_check_score != null ? `${s.best_check_score}` : "\u2014"}
                  </td>
                  <td style={tdStyle}>
                    {s.mastered ? (
                      <span style={{ color: "#16A34A", fontWeight: 600 }}>{t("admin.yes", "Yes")}</span>
                    ) : (
                      <span style={{ color: "#94A3B8" }}>{t("admin.no", "No")}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {total > LIMIT && (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "16px", marginTop: "20px" }}>
          <span style={{ fontSize: "14px", color: "#94A3B8" }}>
            {t("admin.showing", "Showing {{from}}\u2013{{to}} of {{total}}", { from, to, total })}
          </span>
          <div style={{ display: "flex", gap: "8px" }}>
            <button
              onClick={() => setOffset((o) => Math.max(0, o - LIMIT))}
              disabled={offset === 0}
              style={offset === 0 ? pillBtnDisabled : pillBtnStyle}
            >
              {t("admin.prev", "Prev")}
            </button>
            <button
              onClick={() => setOffset((o) => o + LIMIT)}
              disabled={to >= total}
              style={to >= total ? pillBtnDisabled : pillBtnStyle}
            >
              {t("admin.next", "Next")}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
