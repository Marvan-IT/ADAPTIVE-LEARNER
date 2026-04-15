import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Zap, Star, Flame, Target, Save, ShieldOff, ShieldCheck, KeyRound, Award, Trash2 } from "lucide-react";
import {
  getAdminStudentDetail,
  updateAdminStudent,
  toggleStudentAccess,
  resetStudentPassword,
  grantStudentMastery,
  revokeStudentMastery,
} from "../api/admin";
import { getStudentBadges } from "../api/students";
import { useToast } from "../components/ui/Toast";
import BadgeGrid from "../components/game/BadgeGrid";

const LANGUAGES = ["en", "ar", "de", "es", "fr", "hi", "ja", "ko", "ml", "pt", "si", "ta", "zh"];

const STAT_COLORS = [
  { bg: "#FEF3C7", color: "#F59E0B" },
  { bg: "#FFEDD5", color: "#EA580C" },
  { bg: "#FEE2E2", color: "#EF4444" },
  { bg: "#DCFCE7", color: "#22C55E" },
];

const PHASE_COLORS = {
  PRESENTING: { bg: "#FEF9C3", color: "#854D0E" },
  CARDS: { bg: "#DBEAFE", color: "#1E40AF" },
  CHECKING: { bg: "#F3E8FF", color: "#6B21A8" },
  SOCRATIC: { bg: "#F3E8FF", color: "#6B21A8" },
  COMPLETED: { bg: "#DCFCE7", color: "#166534" },
  REMEDIATING: { bg: "#FFEDD5", color: "#9A3412" },
};

const sectionCard = {
  borderRadius: "16px", border: "1px solid #E2E8F0", backgroundColor: "#FFFFFF", padding: "24px", marginBottom: "24px",
};

const sectionTitle = {
  fontSize: "18px", fontWeight: 600, color: "#0F172A", fontFamily: "'Outfit', sans-serif", marginBottom: "20px",
};

const inputStyle = {
  width: "100%", borderRadius: "10px", border: "1px solid #E2E8F0", backgroundColor: "#FFFFFF",
  padding: "10px 14px", fontSize: "14px", color: "#0F172A", outline: "none", boxSizing: "border-box",
};

const labelStyle = {
  display: "block", fontSize: "13px", fontWeight: 500, color: "#0F172A", marginBottom: "6px",
};

const pillBtn = (bg) => ({
  display: "inline-flex", alignItems: "center", gap: "8px", borderRadius: "9999px",
  padding: "10px 20px", fontSize: "14px", fontWeight: 600, color: "#FFFFFF",
  backgroundColor: bg, border: "none", cursor: "pointer", transition: "opacity 0.15s",
});

const thStyle = {
  padding: "12px 14px", textAlign: "left", fontSize: "12px", fontWeight: 600,
  textTransform: "uppercase", letterSpacing: "0.05em", color: "#64748B", backgroundColor: "#F8FAFC",
};

const tdStyle = {
  padding: "12px 14px", fontSize: "14px", color: "#0F172A", borderTop: "1px solid #F1F5F9",
};

export default function AdminStudentDetailPage() {
  const { t } = useTranslation();
  const { id } = useParams();
  const navigate = useNavigate();
  const { toast } = useToast();

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [displayName, setDisplayName] = useState("");
  const [age, setAge] = useState("");
  const [preferredLanguage, setPreferredLanguage] = useState("en");
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState(null);

  const [resetting, setResetting] = useState(false);
  const [resetMsg, setResetMsg] = useState(null);
  const [toggling, setToggling] = useState(false);
  const [grantConceptId, setGrantConceptId] = useState("");
  const [granting, setGranting] = useState(false);
  const [revokingId, setRevokingId] = useState(null);
  const [badges, setBadges] = useState([]);

  const load = () => {
    setLoading(true);
    setError(null);
    getAdminStudentDetail(id)
      .then((r) => {
        const d = r.data;
        // Backend returns { profile, stats, recent_sessions, mastery_list }
        // Normalize to { student, stats, sessions, mastery }
        const normalized = {
          student: d.profile || d.student || {},
          stats: d.stats || {},
          sessions: d.recent_sessions || d.sessions || [],
          mastery: d.mastery_list || d.mastery || [],
        };
        setData(normalized);
        setDisplayName(normalized.student.display_name || "");
        setAge(normalized.student.age ?? "");
        setPreferredLanguage(normalized.student.preferred_language || "en");
      })
      .catch((e) => setError(e.response?.data?.detail || t("admin.loadError", "Failed to load student")))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, [id]);

  useEffect(() => {
    if (id) {
      getStudentBadges(id).then((r) => setBadges(r.data?.badges || r.data || [])).catch(() => {});
    }
  }, [id]);

  const handleSave = async () => {
    setSaving(true);
    setSaveMsg(null);
    try {
      await updateAdminStudent(id, {
        display_name: displayName,
        age: age === "" ? null : Number(age),
        preferred_language: preferredLanguage,
      });
      setSaveMsg({ type: "success", text: t("admin.saveSuccess", "Saved successfully") });
      load();
    } catch (e) {
      setSaveMsg({ type: "error", text: e.response?.data?.detail || t("admin.saveError", "Failed to save") });
    } finally {
      setSaving(false);
    }
  };

  const handleToggleAccess = async () => {
    if (!data) return;
    setToggling(true);
    try {
      await toggleStudentAccess(id, !data.student.is_active);
      load();
    } catch (e) {
      toast({ variant: "danger", title: "Error", description: e.response?.data?.detail || t("admin.toggleError", "Failed to toggle access") });
    } finally {
      setToggling(false);
    }
  };

  const handleResetPassword = async () => {
    setResetting(true);
    setResetMsg(null);
    try {
      const r = await resetStudentPassword(id);
      setResetMsg({ type: "success", text: r.data?.message || t("admin.resetSuccess", "Password reset email sent") });
    } catch (e) {
      setResetMsg({ type: "error", text: e.response?.data?.detail || t("admin.resetError", "Failed to reset password") });
    } finally {
      setResetting(false);
    }
  };

  const handleRevoke = async (conceptId) => {
    setRevokingId(conceptId);
    try {
      await revokeStudentMastery(id, conceptId);
      load();
    } catch (e) {
      toast({ variant: "danger", title: "Error", description: e.response?.data?.detail || t("admin.revokeError", "Failed to revoke mastery") });
    } finally {
      setRevokingId(null);
    }
  };

  const handleGrant = async () => {
    if (!grantConceptId.trim()) return;
    setGranting(true);
    try {
      await grantStudentMastery(id, grantConceptId.trim());
      setGrantConceptId("");
      load();
    } catch (e) {
      toast({ variant: "danger", title: "Error", description: e.response?.data?.detail || t("admin.grantError", "Failed to grant mastery") });
    } finally {
      setGranting(false);
    }
  };

  if (loading) {
    return <div style={{ padding: "64px 0", textAlign: "center", color: "#94A3B8", fontSize: "14px" }}>{t("admin.loading", "Loading...")}</div>;
  }

  if (error) {
    return (
      <div style={{ padding: "64px 0", textAlign: "center" }}>
        <p style={{ color: "#DC2626", marginBottom: "16px" }}>{error}</p>
      </div>
    );
  }

  const student = data?.student || {};
  const mastery = data?.mastery || [];
  const sessions = data?.sessions || [];
  const stats = data?.stats || {};

  const level = Math.floor((student.xp || 0) / 100) + 1;
  const accuracyPct = student.overall_accuracy_rate != null
    ? `${Math.round(student.overall_accuracy_rate * 100)}%`
    : "\u2014";

  const statValues = [
    { label: t("admin.xp", "XP"), value: student.xp ?? 0, Icon: Zap },
    { label: t("admin.level", "Level"), value: level, Icon: Star },
    { label: t("admin.streak", "Streak"), value: student.streak ?? 0, Icon: Flame },
    { label: t("admin.accuracy", "Accuracy"), value: accuracyPct, Icon: Target },
  ];

  return (
    <div style={{ margin: "0 auto" }}>
      {/* Header: avatar + name + status */}
      <div style={{ display: "flex", alignItems: "center", gap: "16px", marginBottom: "28px" }}>
        <div style={{
          width: "64px", height: "64px", borderRadius: "50%", backgroundColor: "#FFEDD5", color: "#EA580C",
          display: "flex", alignItems: "center", justifyContent: "center", fontSize: "22px", fontWeight: 700, flexShrink: 0,
        }}>
          {(student.display_name || "?").split(" ").map((w) => w[0]).join("").slice(0, 2).toUpperCase()}
        </div>
        <div>
          <h1 style={{ fontSize: "26px", fontWeight: 700, color: "#0F172A", fontFamily: "'Outfit', sans-serif", marginBottom: "4px" }}>
            {student.display_name || student.email || t("admin.unknownStudent", "Unknown Student")}
          </h1>
          {student.email && student.display_name && (
            <p style={{ fontSize: "13px", color: "#64748B", marginBottom: "2px" }}>{student.email}</p>
          )}
          <span style={{
            display: "inline-block", borderRadius: "9999px", padding: "3px 12px", fontSize: "12px", fontWeight: 600,
            backgroundColor: student.is_active ? "#DCFCE7" : "#FEE2E2",
            color: student.is_active ? "#166534" : "#991B1B",
          }}>
            {student.is_active ? t("admin.active", "Active") : t("admin.inactive", "Inactive")}
          </span>
        </div>
      </div>

      {/* Stats row */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "16px", marginBottom: "28px" }}>
        {statValues.map((s, i) => {
          const sc = STAT_COLORS[i];
          return (
            <div key={s.label} style={{ borderRadius: "16px", border: "1px solid #E2E8F0", backgroundColor: "#FFFFFF", padding: "20px", textAlign: "center" }}>
              <div style={{ width: "44px", height: "44px", borderRadius: "50%", backgroundColor: sc.bg, color: sc.color, display: "inline-flex", alignItems: "center", justifyContent: "center", marginBottom: "10px" }}>
                <s.Icon size={20} />
              </div>
              <div style={{ fontSize: "28px", fontWeight: 700, color: "#0F172A", fontFamily: "'Outfit', sans-serif" }}>{s.value}</div>
              <div style={{ fontSize: "12px", color: "#94A3B8", marginTop: "4px", fontWeight: 500 }}>{s.label}</div>
            </div>
          );
        })}
      </div>

      {/* Profile Section */}
      <div style={sectionCard}>
        <h2 style={sectionTitle}>{t("admin.profileSection", "Profile")}</h2>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "16px", marginBottom: "20px" }}>
          <div>
            <label style={labelStyle}>{t("admin.displayName", "Display Name")}</label>
            <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} style={inputStyle} />
          </div>
          <div>
            <label style={labelStyle}>{t("admin.age", "Age")}</label>
            <input type="number" value={age} onChange={(e) => setAge(e.target.value)} min={0} max={120} style={inputStyle} />
          </div>
          <div>
            <label style={labelStyle}>{t("admin.preferredLanguage", "Preferred Language")}</label>
            <select value={preferredLanguage} onChange={(e) => setPreferredLanguage(e.target.value)} style={inputStyle}>
              {LANGUAGES.map((l) => <option key={l} value={l}>{l}</option>)}
            </select>
          </div>
        </div>

        {saveMsg && (
          <div style={{
            borderRadius: "10px", padding: "12px", marginBottom: "16px", fontSize: "14px",
            backgroundColor: saveMsg.type === "success" ? "#F0FDF4" : "#FEF2F2",
            color: saveMsg.type === "success" ? "#166534" : "#991B1B",
            border: saveMsg.type === "success" ? "1px solid #BBF7D0" : "1px solid #FECACA",
          }}>
            {saveMsg.text}
          </div>
        )}

        <div style={{ display: "flex", flexWrap: "wrap", gap: "12px" }}>
          <button onClick={handleSave} disabled={saving} style={{ ...pillBtn("#F97316"), opacity: saving ? 0.5 : 1 }}>
            <Save size={15} /> {saving ? t("admin.saving", "Saving...") : t("admin.save", "Save Changes")}
          </button>
          <button onClick={handleToggleAccess} disabled={toggling} style={{ ...pillBtn(student.is_active ? "#EF4444" : "#22C55E"), opacity: toggling ? 0.5 : 1 }}>
            {student.is_active ? <ShieldOff size={15} /> : <ShieldCheck size={15} />}
            {student.is_active ? t("admin.deactivate", "Deactivate Account") : t("admin.activate", "Activate Account")}
          </button>
          <button onClick={handleResetPassword} disabled={resetting} style={{ ...pillBtn("#64748B"), opacity: resetting ? 0.5 : 1 }}>
            <KeyRound size={15} /> {resetting ? t("admin.resetting", "Sending...") : t("admin.resetPassword", "Reset Password")}
          </button>
        </div>

        {resetMsg && (
          <div style={{
            marginTop: "12px", borderRadius: "10px", padding: "12px", fontSize: "14px",
            backgroundColor: resetMsg.type === "success" ? "#F0FDF4" : "#FEF2F2",
            color: resetMsg.type === "success" ? "#166534" : "#991B1B",
            border: resetMsg.type === "success" ? "1px solid #BBF7D0" : "1px solid #FECACA",
          }}>
            {resetMsg.text}
          </div>
        )}
      </div>

      {/* Extended Stats */}
      <div style={sectionCard}>
        <h2 style={sectionTitle}>{t("admin.stats", "Stats")}</h2>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "12px" }}>
          {[
            { label: t("admin.sectionsCompleted", "Sections"), value: student.section_count ?? 0 },
            { label: t("admin.conceptsMastered", "Mastered"), value: mastery.length },
            { label: t("admin.totalSessions", "Sessions"), value: stats.total_sessions ?? sessions.length },
            { label: t("admin.totalCards", "Cards"), value: stats.total_cards ?? "\u2014" },
          ].map((s) => (
            <div key={s.label} style={{ borderRadius: "12px", border: "1px solid #E2E8F0", padding: "16px", textAlign: "center" }}>
              <div style={{ fontSize: "22px", fontWeight: 700, color: "#0F172A", fontFamily: "'Outfit', sans-serif" }}>{s.value}</div>
              <div style={{ fontSize: "12px", color: "#94A3B8", marginTop: "4px" }}>{s.label}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Mastery List */}
      <div style={sectionCard}>
        <h2 style={sectionTitle}>{t("admin.masteryList", "Concept Mastery")}</h2>

        {mastery.length === 0 ? (
          <p style={{ color: "#94A3B8", fontSize: "14px" }}>{t("admin.noMastery", "No concepts mastered yet.")}</p>
        ) : (
          <div style={{ borderRadius: "12px", overflow: "hidden", border: "1px solid #E2E8F0", marginBottom: "16px" }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  <th style={thStyle}>{t("admin.conceptId", "Concept ID")}</th>
                  <th style={thStyle}>{t("admin.masteredAt", "Mastered At")}</th>
                  <th style={thStyle} />
                </tr>
              </thead>
              <tbody>
                {mastery.map((m) => (
                  <tr key={m.concept_id}>
                    <td style={{ ...tdStyle, fontWeight: 500 }}>{m.concept_id}</td>
                    <td style={{ ...tdStyle, color: "#64748B" }}>
                      {m.mastered_at ? new Date(m.mastered_at).toLocaleString() : "\u2014"}
                    </td>
                    <td style={tdStyle}>
                      <button
                        onClick={() => handleRevoke(m.concept_id)}
                        disabled={revokingId === m.concept_id}
                        style={{ ...pillBtn("#EF4444"), padding: "5px 12px", fontSize: "12px", opacity: revokingId === m.concept_id ? 0.5 : 1 }}
                      >
                        <Trash2 size={12} /> {t("admin.revoke", "Revoke")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Grant mastery */}
        <div style={{ display: "flex", gap: "12px", alignItems: "center" }}>
          <input
            value={grantConceptId}
            onChange={(e) => setGrantConceptId(e.target.value)}
            placeholder={t("admin.grantConceptPlaceholder", "Concept ID to grant...")}
            style={{ ...inputStyle, flex: 1 }}
          />
          <button
            onClick={handleGrant}
            disabled={granting || !grantConceptId.trim()}
            style={{ ...pillBtn("#22C55E"), whiteSpace: "nowrap", opacity: (granting || !grantConceptId.trim()) ? 0.5 : 1 }}
          >
            <Award size={15} /> {granting ? t("admin.granting", "Granting...") : t("admin.grantMastery", "Grant Mastery")}
          </button>
        </div>
      </div>

      {/* Badges & Progress */}
      <div style={sectionCard}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "20px" }}>
          <h2 style={{ ...sectionTitle, marginBottom: 0 }}>{t("badge.viewAll", "Badges")}</h2>
          <button onClick={() => navigate(`/admin/students/${id}/progress`)} style={pillBtn("#F97316")}>
            {t("progress.report", "View Progress Report")}
          </button>
        </div>
        <BadgeGrid earnedBadges={badges} />
      </div>

      {/* Session History */}
      <div style={{ ...sectionCard, marginBottom: 0 }}>
        <h2 style={sectionTitle}>{t("admin.sessionHistory", "Session History")}</h2>
        {sessions.length === 0 ? (
          <p style={{ color: "#94A3B8", fontSize: "14px" }}>{t("admin.noSessions", "No sessions yet.")}</p>
        ) : (
          <div style={{ borderRadius: "12px", overflow: "hidden", border: "1px solid #E2E8F0" }}>
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr>
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
                  {sessions.map((s) => {
                    const pc = PHASE_COLORS[s.phase] || { bg: "#F1F5F9", color: "#475569" };
                    return (
                      <tr key={s.id}
                        style={{ transition: "background-color 0.15s" }}
                        onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = "#FFF7ED"; }}
                        onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = ""; }}
                      >
                        <td style={{ ...tdStyle, fontWeight: 500, maxWidth: "200px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={s.concept_id}>
                          {s.concept_id}
                        </td>
                        <td style={{ ...tdStyle, color: "#64748B" }}>{s.book_slug || "\u2014"}</td>
                        <td style={tdStyle}>
                          <span style={{ display: "inline-block", borderRadius: "9999px", padding: "3px 10px", fontSize: "12px", fontWeight: 600, backgroundColor: pc.bg, color: pc.color }}>
                            {s.phase}
                          </span>
                        </td>
                        <td style={{ ...tdStyle, color: "#64748B", whiteSpace: "nowrap" }}>
                          {(s.started_at || s.created_at) ? new Date(s.started_at || s.created_at).toLocaleDateString() : "\u2014"}
                        </td>
                        <td style={{ ...tdStyle, color: "#64748B", whiteSpace: "nowrap" }}>
                          {s.completed_at ? new Date(s.completed_at).toLocaleDateString() : "\u2014"}
                        </td>
                        <td style={tdStyle}>{(s.check_score ?? s.best_check_score) != null ? `${s.check_score ?? s.best_check_score}` : "\u2014"}</td>
                        <td style={tdStyle}>
                          {(s.concept_mastered ?? s.mastered)
                            ? <span style={{ fontWeight: 600, color: "#16A34A" }}>{t("admin.yes", "Yes")}</span>
                            : <span style={{ color: "#94A3B8" }}>{t("admin.no", "No")}</span>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
