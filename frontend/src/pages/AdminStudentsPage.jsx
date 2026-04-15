import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Search } from "lucide-react";
import { getAdminStudents, toggleStudentAccess } from "../api/admin";
import { useToast } from "../components/ui/Toast";

const LIMIT = 50;

const AVATAR_COLORS = [
  { bg: "#FFEDD5", color: "#EA580C" },
  { bg: "#DBEAFE", color: "#2563EB" },
  { bg: "#DCFCE7", color: "#16A34A" },
  { bg: "#F3E8FF", color: "#9333EA" },
  { bg: "#FCE7F3", color: "#DB2777" },
  { bg: "#CFFAFE", color: "#0891B2" },
];

const COLUMNS = [
  { key: "display_name", label: "Name" },
  { key: "email", label: "Email" },
  { key: "age", label: "Age" },
  { key: "xp", label: "XP" },
  { key: "streak", label: "Streak" },
  { key: "concepts_mastered", label: "Mastery" },
  { key: "overall_accuracy_rate", label: "Accuracy" },
  { key: "is_active", label: "Status" },
];

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
  cursor: "pointer",
  userSelect: "none",
  borderBottom: "1px solid #E2E8F0",
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

function AvatarCircle({ name }) {
  const initials = (name || "?")
    .split(" ")
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
  const palette = AVATAR_COLORS[(name || "?").charCodeAt(0) % AVATAR_COLORS.length];
  return (
    <div
      style={{
        width: "40px",
        height: "40px",
        borderRadius: "50%",
        backgroundColor: palette.bg,
        color: palette.color,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontSize: "12px",
        fontWeight: 700,
        flexShrink: 0,
      }}
    >
      {initials}
    </div>
  );
}

export default function AdminStudentsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { toast } = useToast();

  const [students, setStudents] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [offset, setOffset] = useState(0);
  const [sortKey, setSortKey] = useState("display_name");
  const [sortDir, setSortDir] = useState("asc");
  const [togglingId, setTogglingId] = useState(null);

  const debounceRef = useRef(null);

  const load = useCallback((searchVal, status, off, sk, sd) => {
    setLoading(true);
    setError(null);
    const params = { limit: LIMIT, offset: off, sort: sk, dir: sd };
    if (searchVal) params.search = searchVal;
    if (status !== "all") params.is_active = status === "active";
    getAdminStudents(params)
      .then((r) => {
        const data = r.data;
        setStudents(data.items ?? (Array.isArray(data) ? data : []));
        setTotal(data.total ?? (Array.isArray(data) ? data.length : 0));
      })
      .catch((e) => setError(e.response?.data?.detail || t("admin.loadError", "Failed to load students")))
      .finally(() => setLoading(false));
  }, [t]);

  useEffect(() => {
    load(search, statusFilter, offset, sortKey, sortDir);
  }, [load, search, statusFilter, offset, sortKey, sortDir]);

  const handleSearchChange = (e) => {
    const val = e.target.value;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      setOffset(0);
      setSearch(val);
    }, 300);
  };

  const handleStatusFilter = (val) => {
    setOffset(0);
    setStatusFilter(val);
  };

  const handleSort = (key) => {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
    setOffset(0);
  };

  const handleToggle = async (student) => {
    setTogglingId(student.id);
    try {
      await toggleStudentAccess(student.id, !student.is_active);
      load(search, statusFilter, offset, sortKey, sortDir);
    } catch (e) {
      toast({ variant: "danger", title: "Error", description: e.response?.data?.detail || t("admin.toggleError", "Failed to toggle access") });
    } finally {
      setTogglingId(null);
    }
  };

  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + LIMIT, total);

  const sortIndicator = (key) => {
    if (key !== sortKey) return " \u21D5";
    return sortDir === "asc" ? " \u2191" : " \u2193";
  };

  const filters = ["all", "active", "inactive"];

  const totalPages = Math.ceil(total / LIMIT);
  const currentPage = Math.floor(offset / LIMIT) + 1;

  return (
    <div style={{ margin: "0 auto" }}>
      {/* Header */}
      <div style={{ marginBottom: "20px" }}>
        <h1 style={{ fontSize: "26px", fontWeight: 700, color: "#0F172A", fontFamily: "'Outfit', sans-serif", marginBottom: "4px" }}>
          {t("admin.studentManagement", "Student Management")}
        </h1>
        {total > 0 && (
          <p style={{ fontSize: "14px", color: "#64748B", marginTop: "4px" }}>
            {t("admin.totalStudents", "{{count}} students", { count: total })}
          </p>
        )}
      </div>

      {/* Search */}
      <div style={{ position: "relative", marginBottom: "16px" }}>
        <Search
          size={18}
          style={{ position: "absolute", left: "16px", top: "50%", transform: "translateY(-50%)", color: "#94A3B8", pointerEvents: "none" }}
          aria-hidden="true"
        />
        <input
          defaultValue=""
          onChange={handleSearchChange}
          placeholder={t("admin.searchStudents", "Search by name or email...")}
          style={{
            width: "100%",
            height: "44px",
            borderRadius: "9999px",
            border: "1px solid #E2E8F0",
            padding: "0 16px 0 44px",
            fontSize: "14px",
            outline: "none",
            color: "#0F172A",
            backgroundColor: "#FFFFFF",
            boxSizing: "border-box",
          }}
        />
      </div>

      {/* Filter tabs */}
      <div style={{ display: "flex", gap: "24px", marginBottom: "24px", borderBottom: "1px solid #E2E8F0", paddingBottom: "0" }} role="group" aria-label={t("admin.filterLabel", "Filter by status")}>
        {filters.map((f) => {
          const isActive = statusFilter === f;
          return (
            <button
              key={f}
              onClick={() => handleStatusFilter(f)}
              aria-pressed={isActive}
              style={{
                background: "none",
                border: "none",
                borderBottom: isActive ? "2px solid #F97316" : "2px solid transparent",
                color: isActive ? "#F97316" : "#64748B",
                fontWeight: isActive ? 600 : 500,
                fontSize: "14px",
                paddingBottom: "12px",
                cursor: "pointer",
                transition: "color 0.15s, border-color 0.15s",
              }}
            >
              {f === "all"
                ? t("admin.filterAll", "All")
                : f === "active"
                ? t("admin.filterActive", "Active")
                : t("admin.filterInactive", "Inactive")}
            </button>
          );
        })}
      </div>

      {/* Error */}
      {error && (
        <div style={{ padding: "12px 16px", backgroundColor: "#FEF2F2", border: "1px solid #FECACA", borderRadius: "12px", color: "#DC2626", marginBottom: "16px", fontSize: "14px" }}>
          {error}
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div style={{ padding: "64px 0", textAlign: "center", color: "#94A3B8", fontSize: "14px" }}>
          {t("admin.loading", "Loading...")}
        </div>
      )}

      {/* Empty */}
      {!loading && !error && students.length === 0 && (
        <div style={{ padding: "64px 0", textAlign: "center", color: "#94A3B8" }}>
          <p style={{ fontSize: "16px" }}>{t("admin.noStudents", "No students found.")}</p>
        </div>
      )}

      {/* Table */}
      {!loading && students.length > 0 && (
        <div style={tableContainer}>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  {COLUMNS.map((col) => (
                    <th
                      key={col.key}
                      onClick={() => handleSort(col.key)}
                      style={thStyle}
                    >
                      {t(`admin.col.${col.key}`, col.label)}{sortIndicator(col.key)}
                    </th>
                  ))}
                  <th style={{ ...thStyle, cursor: "default" }}></th>
                </tr>
              </thead>
              <tbody>
                {students.map((s) => (
                  <tr
                    key={s.id}
                    style={{ transition: "background-color 0.15s", cursor: "pointer" }}
                    onClick={() => navigate(`/admin/students/${s.id}`)}
                    onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = "#FFF7ED"; }}
                    onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = ""; }}
                  >
                    {/* Name + avatar */}
                    <td style={tdStyle}>
                      <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                        <AvatarCircle name={s.display_name} />
                        <span style={{ fontWeight: 500, color: "#0F172A" }}>{s.display_name || "\u2014"}</span>
                      </div>
                    </td>
                    <td style={{ ...tdStyle, color: "#64748B" }}>{s.email || "\u2014"}</td>
                    <td style={{ ...tdStyle, color: "#64748B" }}>{s.age ?? "\u2014"}</td>
                    <td style={{ ...tdStyle, fontWeight: 500 }}>{s.xp ?? 0}</td>
                    <td style={{ ...tdStyle, fontWeight: 500 }}>{s.streak ?? 0}</td>
                    <td style={{ ...tdStyle, fontWeight: 500 }}>{s.concepts_mastered ?? 0}</td>
                    <td style={{ ...tdStyle, fontWeight: 500 }}>
                      {s.overall_accuracy_rate != null
                        ? `${Math.round(s.overall_accuracy_rate * 100)}%`
                        : "\u2014"}
                    </td>
                    <td style={tdStyle}>
                      <span
                        style={{
                          color: s.is_active ? "#16A34A" : "#DC2626",
                          fontWeight: 600,
                          fontSize: "14px",
                        }}
                      >
                        {s.is_active ? t("admin.active", "Active") : t("admin.inactive", "Inactive")}
                      </span>
                    </td>
                    <td style={tdStyle} onClick={(e) => e.stopPropagation()}>
                      <div style={{ display: "flex", gap: "8px" }}>
                        <button
                          onClick={(e) => { e.stopPropagation(); handleToggle(s); }}
                          disabled={togglingId === s.id}
                          style={{
                            backgroundColor: s.is_active ? "#EF4444" : "#22C55E",
                            color: "#FFF",
                            borderRadius: "9999px",
                            padding: "4px 12px",
                            fontSize: "12px",
                            fontWeight: 600,
                            border: "none",
                            cursor: togglingId === s.id ? "not-allowed" : "pointer",
                            opacity: togglingId === s.id ? 0.5 : 1,
                            transition: "opacity 0.15s",
                          }}
                          onMouseEnter={(e) => { if (togglingId !== s.id) e.currentTarget.style.opacity = "0.85"; }}
                          onMouseLeave={(e) => { if (togglingId !== s.id) e.currentTarget.style.opacity = "1"; }}
                        >
                          {s.is_active ? t("admin.deactivate", "Deactivate") : t("admin.activate", "Activate")}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Pagination */}
      {total > LIMIT && (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: "20px" }}>
          <span style={{ fontSize: "14px", color: "#64748B" }}>
            {t("admin.showing", "Showing {{from}}\u2013{{to}} of {{total}}", { from, to, total })}
          </span>
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <button
              onClick={() => setOffset((o) => Math.max(0, o - LIMIT))}
              disabled={offset === 0}
              style={{
                borderRadius: "9999px",
                padding: "8px 16px",
                fontSize: "14px",
                fontWeight: 500,
                border: "1px solid #E2E8F0",
                backgroundColor: "#FFFFFF",
                color: "#0F172A",
                cursor: offset === 0 ? "not-allowed" : "pointer",
                opacity: offset === 0 ? 0.4 : 1,
              }}
            >
              {t("admin.prev", "Prev")}
            </button>
            <span style={{ borderRadius: "9999px", padding: "8px 16px", fontSize: "14px", fontWeight: 600, backgroundColor: "#F97316", color: "#FFFFFF" }}>
              {currentPage}
            </span>
            <button
              onClick={() => setOffset((o) => o + LIMIT)}
              disabled={to >= total}
              style={{
                borderRadius: "9999px",
                padding: "8px 16px",
                fontSize: "14px",
                fontWeight: 500,
                border: "1px solid #E2E8F0",
                backgroundColor: "#FFFFFF",
                color: "#0F172A",
                cursor: to >= total ? "not-allowed" : "pointer",
                opacity: to >= total ? 0.4 : 1,
              }}
            >
              {t("admin.next", "Next")}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
