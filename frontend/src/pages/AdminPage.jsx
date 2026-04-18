import { useState, useEffect } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Users, Activity, BookOpen, BarChart3, Settings, Plus, Trash2, Eye, EyeOff, Pencil } from "lucide-react";
import { getSubjects, createSubject, deleteSubject, toggleSubjectVisibility, getDashboard } from "../api/admin";
import { useToast } from "../components/ui/Toast";
import { useDialog } from "../context/DialogProvider";

const STAT_ICONS = [
  { Icon: Users, bg: "#DBEAFE", color: "#2563EB" },
  { Icon: Activity, bg: "#DCFCE7", color: "#16A34A" },
  { Icon: BookOpen, bg: "#FFEDD5", color: "#EA580C" },
  { Icon: BarChart3, bg: "#F3E8FF", color: "#9333EA" },
];

const NAV_CARDS = [
  {
    key: "students",
    to: "/admin/students",
    Icon: Users,
    bg: "#DCFCE7",
    color: "#16A34A",
    titleKey: "admin.nav.students",
    titleDefault: "Students",
    descKey: "admin.nav.studentsDesc",
    descDefault: "Manage student accounts, access, and progress",
  },
  {
    key: "sessions",
    to: "/admin/sessions",
    Icon: BookOpen,
    bg: "#CFFAFE",
    color: "#0891B2",
    titleKey: "admin.nav.sessions",
    titleDefault: "Sessions",
    descKey: "admin.nav.sessionsDesc",
    descDefault: "Monitor active and completed learning sessions",
  },
  {
    key: "analytics",
    to: "/admin/analytics",
    Icon: BarChart3,
    bg: "#F3E8FF",
    color: "#9333EA",
    titleKey: "admin.nav.analytics",
    titleDefault: "Analytics",
    descKey: "admin.nav.analyticsDesc",
    descDefault: "View concept difficulty and student performance",
  },
  {
    key: "settings",
    to: "/admin/settings",
    Icon: Settings,
    bg: "#F1F5F9",
    color: "#475569",
    titleKey: "admin.nav.settings",
    titleDefault: "Settings",
    descKey: "admin.nav.settingsDesc",
    descDefault: "Configure platform settings and thresholds",
  },
];

const SUBJECT_COLORS = [
  "#FB923C",
  "#60A5FA",
  "#4ADE80",
  "#C084FC",
  "#FB7185",
  "#22D3EE",
];

const cardStyle = {
  borderRadius: "12px",
  border: "1px solid #E2E8F0",
  backgroundColor: "#FFFFFF",
  padding: "16px",
  boxShadow: "0 1px 2px rgba(0,0,0,0.04)",
};

const sectionHeading = {
  fontSize: "22px",
  fontWeight: 700,
  color: "#0F172A",
  fontFamily: "'Outfit', sans-serif",
  marginBottom: "16px",
};

export default function AdminPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { toast } = useToast();
  const dialog = useDialog();

  const [subjects, setSubjects] = useState([]);
  const [subjectsLoading, setSubjectsLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [newLabel, setNewLabel] = useState("");

  const [dashboard, setDashboard] = useState(null);
  const [dashboardLoading, setDashboardLoading] = useState(true);

  const loadSubjects = () => {
    setSubjectsLoading(true);
    getSubjects()
      .then((r) => setSubjects(r.data))
      .catch(console.error)
      .finally(() => setSubjectsLoading(false));
  };

  useEffect(() => {
    loadSubjects();
    getDashboard()
      .then((r) => setDashboard(r.data))
      .catch(console.error)
      .finally(() => setDashboardLoading(false));
  }, []);

  const handleToggleSubjectVisibility = async (subj) => {
    try {
      await toggleSubjectVisibility(subj.slug, !subj.is_hidden);
      loadSubjects();
    } catch (e) {
      toast({ variant: "danger", title: "Error", description: e.response?.data?.detail || t("admin.toggleVisibilityError", "Failed to toggle visibility") });
    }
  };

  const handleDeleteSubject = async (subj) => {
    if (!(await dialog.confirm({ title: "Delete Subject", message: t("admin.confirmDeleteSubject", `Delete subject "${subj.label}"? This cannot be undone.`), variant: "danger", confirmLabel: "Delete" }))) return;
    try {
      await deleteSubject(subj.slug);
      loadSubjects();
    } catch (e) {
      toast({ variant: "danger", title: "Error", description: e.response?.data?.detail || t("admin.deleteSubjectError", "Failed to delete subject") });
    }
  };

  const handleAddSubject = () => {
    if (!newLabel.trim()) return;
    createSubject(newLabel.trim())
      .then(() => {
        setNewLabel("");
        setShowForm(false);
        loadSubjects();
      })
      .catch((e) =>
        toast({ variant: "danger", title: "Error", description: e.response?.data?.detail || t("admin.subjectCreateError", "Failed to create subject") })
      );
  };

  const statCards = [
    {
      key: "totalStudents",
      label: t("admin.stats.totalStudents", "Total Students"),
      value: dashboard?.total_students ?? "\u2014",
    },
    {
      key: "active7d",
      label: t("admin.stats.active7d", "Active (7d)"),
      value: dashboard?.active_7d ?? "\u2014",
    },
    {
      key: "sessionsWeek",
      label: t("admin.stats.sessionsThisWeek", "Sessions This Week"),
      value: dashboard?.sessions_this_week ?? "\u2014",
    },
    {
      key: "masteryRate",
      label: t("admin.stats.masteryRate", "Mastery Rate"),
      value:
        dashboard?.avg_mastery_rate != null
          ? `${Math.round(dashboard.avg_mastery_rate * 100)}%`
          : "\u2014",
    },
  ];

  return (
    <div style={{ margin: "0 auto" }}>
      {/* Header */}
      <div style={{ marginBottom: "28px" }}>
        <h1 style={{ fontSize: "28px", fontWeight: 700, color: "#0F172A", fontFamily: "'Outfit', sans-serif", marginBottom: "4px" }}>
          {t("admin.title", "Dashboard")}
        </h1>
        <p style={{ fontSize: "14px", color: "#64748B" }}>
          {t("admin.subtitle", "Welcome back! Here's what's happening")}
        </p>
      </div>

      {/* Stats Row */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "16px", marginBottom: "28px" }}>
        {statCards.map((s, i) => {
          const { Icon, bg, color } = STAT_ICONS[i];
          return (
            <div key={s.key} style={{ ...cardStyle }}>
              <div
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  width: "40px",
                  height: "40px",
                  borderRadius: "50%",
                  backgroundColor: bg,
                  marginBottom: "10px",
                }}
              >
                <Icon size={22} color={color} aria-hidden="true" />
              </div>
              <p style={{ fontSize: "12px", fontWeight: 500, color: "#64748B", marginBottom: "4px" }}>
                {s.label}
              </p>
              <p style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", fontFamily: "'Outfit', sans-serif" }}>
                {dashboardLoading ? (
                  <span style={{ fontSize: "16px", color: "#94A3B8" }}>
                    {t("admin.loading", "Loading...")}
                  </span>
                ) : (
                  s.value
                )}
              </p>
            </div>
          );
        })}
      </div>

      {/* Nav Cards Grid */}
      <h2 style={sectionHeading}>
        {t("admin.manage", "Manage")}
      </h2>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "16px", marginBottom: "28px" }}>
        {NAV_CARDS.map((card) => (
          <Link
            key={card.key}
            to={card.to}
            style={{
              ...cardStyle,
              textDecoration: "none",
              display: "block",
              cursor: "pointer",
              transition: "box-shadow 0.15s, transform 0.15s",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.boxShadow = "0 4px 12px rgba(0,0,0,0.08)";
              e.currentTarget.style.transform = "translateY(-2px)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.boxShadow = "0 1px 2px rgba(0,0,0,0.04)";
              e.currentTarget.style.transform = "translateY(0)";
            }}
          >
            <div
              style={{
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                width: "40px",
                height: "40px",
                borderRadius: "50%",
                backgroundColor: card.bg,
                marginBottom: "10px",
              }}
            >
              <card.Icon size={22} color={card.color} aria-hidden="true" />
            </div>
            <h3 style={{ fontSize: "14px", fontWeight: 600, color: "#0F172A", marginBottom: "3px" }}>
              {t(card.titleKey, card.titleDefault)}
            </h3>
            <p style={{ fontSize: "13px", color: "#64748B", lineHeight: 1.4 }}>
              {t(card.descKey, card.descDefault)}
            </p>
          </Link>
        ))}
      </div>

      {/* Subjects Section */}
      <h2 style={sectionHeading}>
        {t("admin.subjects", "Subjects")}
      </h2>

      {subjectsLoading ? (
        <div style={{ fontSize: "14px", color: "#94A3B8" }}>
          {t("admin.loading", "Loading...")}
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: "16px" }}>
          {subjects.map((s, i) => (
            <div
              key={s.slug}
              style={{
                ...cardStyle,
                borderTop: `4px solid ${SUBJECT_COLORS[i % SUBJECT_COLORS.length]}`,
                position: "relative",
                opacity: s.is_hidden ? 0.55 : 1,
              }}
            >
              {/* Top-right action buttons */}
              <div style={{ position: "absolute", top: "10px", right: "10px", display: "flex", gap: "4px" }}>
                <button
                  onClick={() => handleToggleSubjectVisibility(s)}
                  title={s.is_hidden ? t("admin.unhideSubject", "Show to students") : t("admin.hideSubject", "Hide from students")}
                  style={{
                    width: "28px", height: "28px", borderRadius: "50%",
                    border: "none", backgroundColor: "transparent", cursor: "pointer",
                    display: "flex", alignItems: "center", justifyContent: "center",
                    transition: "background-color 0.15s",
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = s.is_hidden ? "#DCFCE7" : "#FEF3C7"; }}
                  onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = "transparent"; }}
                >
                  {s.is_hidden ? <Eye size={14} color="#22C55E" /> : <EyeOff size={14} color="#F59E0B" />}
                </button>
                <button
                  onClick={async () => {
                    const newLabel = prompt("Rename subject:", s.label);
                    if (newLabel && newLabel.trim() && newLabel.trim() !== s.label) {
                      try {
                        const api = await import("../api/client");
                        await api.default.put(`/api/admin/subjects/${s.slug}`, { label: newLabel.trim() });
                        loadSubjects();
                      } catch (e) {
                        toast({ variant: "danger", title: "Error", description: e.response?.data?.detail || "Failed to rename subject" });
                      }
                    }
                  }}
                  title="Rename subject"
                  style={{
                    width: "28px", height: "28px", borderRadius: "50%",
                    border: "none", backgroundColor: "transparent", cursor: "pointer",
                    display: "flex", alignItems: "center", justifyContent: "center",
                    transition: "background-color 0.15s",
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = "#E0F2FE"; }}
                  onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = "transparent"; }}
                >
                  <Pencil size={14} color="#3B82F6" />
                </button>
                <button
                  onClick={() => handleDeleteSubject(s)}
                  title={t("admin.deleteSubject", "Delete subject")}
                  style={{
                    width: "28px", height: "28px", borderRadius: "50%",
                    border: "none", backgroundColor: "transparent", cursor: "pointer",
                    display: "flex", alignItems: "center", justifyContent: "center",
                    transition: "background-color 0.15s",
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = "#FEE2E2"; }}
                  onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = "transparent"; }}
                >
                  <Trash2 size={14} color="#EF4444" />
                </button>
              </div>

              {/* Hidden badge */}
              {s.is_hidden && (
                <span style={{ display: "inline-block", fontSize: "11px", fontWeight: 600, color: "#F59E0B", backgroundColor: "#FEF3C7", padding: "2px 8px", borderRadius: "4px", marginBottom: "8px" }}>
                  Hidden
                </span>
              )}

              <h3 style={{ fontSize: "18px", fontWeight: 600, color: "#0F172A", marginBottom: "8px", paddingRight: "60px" }}>
                {s.label}
              </h3>
              <p style={{ fontSize: "14px", color: "#64748B", marginBottom: "16px" }}>
                {s.book_count}{" "}
                {s.book_count !== 1
                  ? t("admin.books", "books")
                  : t("admin.book", "book")}
              </p>
              <button
                onClick={() => navigate(`/admin/subjects/${s.slug}`)}
                style={{
                  width: "100%",
                  borderRadius: "9999px",
                  backgroundColor: "#F97316",
                  padding: "10px 0",
                  fontSize: "14px",
                  fontWeight: 600,
                  color: "#FFFFFF",
                  border: "none",
                  cursor: "pointer",
                  transition: "background-color 0.15s",
                }}
                onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = "#EA580C"; }}
                onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = "#F97316"; }}
              >
                {t("admin.open", "Open")}
              </button>
            </div>
          ))}

          {/* Add Subject — inline form or dashed card */}
          {showForm ? (
            <div style={{ ...cardStyle, border: "2px solid #F97316", display: "flex", flexDirection: "column", gap: "10px", justifyContent: "center", minHeight: "140px" }}>
              <input
                value={newLabel}
                onChange={(e) => setNewLabel(e.target.value)}
                placeholder={t("admin.subjectPlaceholder", "Subject name (e.g. Physics)")}
                autoFocus
                onKeyDown={(e) => { if (e.key === "Enter") handleAddSubject(); }}
                style={{
                  borderRadius: "8px", border: "1px solid #E2E8F0", backgroundColor: "#F8FAFC",
                  padding: "10px 12px", fontSize: "14px", color: "#0F172A", outline: "none", width: "100%", boxSizing: "border-box",
                }}
              />
              <div style={{ display: "flex", gap: "8px" }}>
                <button
                  onClick={handleAddSubject}
                  style={{ flex: 1, borderRadius: "9999px", backgroundColor: "#22C55E", padding: "8px 0", fontSize: "13px", fontWeight: 600, color: "#FFFFFF", border: "none", cursor: "pointer" }}
                >
                  {t("admin.create", "Create")}
                </button>
                <button
                  onClick={() => { setShowForm(false); setNewLabel(""); }}
                  style={{ flex: 1, borderRadius: "9999px", backgroundColor: "#94A3B8", padding: "8px 0", fontSize: "13px", fontWeight: 600, color: "#FFFFFF", border: "none", cursor: "pointer" }}
                >
                  {t("admin.cancel", "Cancel")}
                </button>
              </div>
            </div>
          ) : (
            <button
              onClick={() => setShowForm(true)}
              style={{
                ...cardStyle,
                border: "2px dashed #CBD5E1",
                cursor: "pointer",
                textAlign: "center",
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                gap: "8px",
                minHeight: "140px",
                backgroundColor: "transparent",
                transition: "border-color 0.15s, background-color 0.15s",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = "#F97316";
                e.currentTarget.style.backgroundColor = "rgba(249,115,22,0.05)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = "#CBD5E1";
                e.currentTarget.style.backgroundColor = "transparent";
              }}
            >
              <div style={{ width: "40px", height: "40px", borderRadius: "50%", backgroundColor: "#E2E8F0", display: "flex", alignItems: "center", justifyContent: "center" }}>
                <Plus size={22} color="#94A3B8" aria-hidden="true" />
              </div>
              <span style={{ fontSize: "14px", fontWeight: 500, color: "#94A3B8" }}>
                {t("admin.addSubject", "Add Subject")}
              </span>
            </button>
          )}
        </div>
      )}
    </div>
  );
}
