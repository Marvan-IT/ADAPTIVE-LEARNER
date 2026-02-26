import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useStudent } from "../../context/StudentContext";
import { useTheme } from "../../context/ThemeContext";
import { listStudents } from "../../api/students";
import { trackEvent } from "../../utils/analytics";
import { User, UserPlus, Trophy, Loader } from "lucide-react";

export default function StudentPicker({ onCreateNew }) {
  const { t } = useTranslation();
  const [students, setStudents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const { selectStudent } = useStudent();
  const { setStyle } = useTheme();
  const navigate = useNavigate();

  useEffect(() => {
    listStudents()
      .then((res) => {
        setStudents(res.data);
        trackEvent("student_picker_viewed", { student_count: res.data.length });
      })
      .catch((err) => setError(err.response?.data?.detail || t("welcome.loadError")))
      .finally(() => setLoading(false));
  }, []);

  const handleSelect = async (s) => {
    await selectStudent(s);
    if (s.preferred_style) setStyle(s.preferred_style);
    trackEvent("student_selected", {
      student_id: s.id,
      student_name: s.display_name,
      preferred_style: s.preferred_style,
      interests: s.interests,
      mastered_count: s.mastered_count || 0,
    });
    navigate("/map");
  };

  if (loading) {
    return (
      <div style={{ textAlign: "center", padding: "2rem" }}>
        <Loader size={28} color="var(--color-primary)" style={{ animation: "spin 1s linear infinite" }} />
        <p style={{ color: "var(--color-text-muted)", marginTop: "0.5rem" }}>{t("welcome.loadingStudents")}</p>
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ textAlign: "center", padding: "1rem", color: "var(--color-danger)" }}>
        <p>{error}</p>
      </div>
    );
  }

  return (
    <div>
      <h2 style={{ fontSize: "1.3rem", fontWeight: 700, color: "var(--color-text)", marginBottom: "0.3rem" }}>
        {t("welcome.title")}
      </h2>
      <p style={{ fontSize: "0.9rem", color: "var(--color-text-muted)", marginBottom: "1.25rem" }}>
        {t("welcome.subtitle")}
      </p>

      {students.length === 0 ? (
        <p style={{ textAlign: "center", color: "var(--color-text-muted)", padding: "1rem 0" }}>
          {t("welcome.noStudents")}
        </p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.6rem", marginBottom: "1rem", maxHeight: "320px", overflowY: "auto" }}>
          {students.map((s) => (
            <button
              key={s.id}
              onClick={() => handleSelect(s)}
              style={{
                display: "flex", alignItems: "center", gap: "0.75rem",
                padding: "0.8rem 1rem", borderRadius: "12px",
                border: "2px solid var(--color-border)",
                backgroundColor: "var(--color-bg)",
                cursor: "pointer", fontFamily: "inherit",
                textAlign: "left", width: "100%",
                transition: "all 0.2s",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = "var(--color-primary)";
                e.currentTarget.style.backgroundColor = "var(--color-primary-light)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = "var(--color-border)";
                e.currentTarget.style.backgroundColor = "var(--color-bg)";
              }}
            >
              <div style={{
                width: "42px", height: "42px", borderRadius: "50%",
                backgroundColor: "var(--color-primary)",
                display: "flex", alignItems: "center", justifyContent: "center",
                color: "#fff", flexShrink: 0,
              }}>
                <User size={20} />
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 700, fontSize: "1rem", color: "var(--color-text)" }}>
                  {s.display_name}
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontSize: "0.8rem", color: "var(--color-text-muted)" }}>
                  {s.mastered_count > 0 && (
                    <span style={{ display: "flex", alignItems: "center", gap: "0.2rem", color: "var(--color-success)", fontWeight: 600 }}>
                      <Trophy size={12} /> {t("welcome.masteredCount", { count: s.mastered_count })}
                    </span>
                  )}
                  {s.interests?.length > 0 && (
                    <span>{s.interests.slice(0, 3).join(", ")}</span>
                  )}
                </div>
              </div>
            </button>
          ))}
        </div>
      )}

      <button
        onClick={() => {
          trackEvent("create_new_student_clicked");
          onCreateNew();
        }}
        style={{
          display: "flex", alignItems: "center", justifyContent: "center", gap: "0.5rem",
          width: "100%", padding: "0.75rem",
          borderRadius: "12px", border: "2px dashed var(--color-border)",
          backgroundColor: "transparent", color: "var(--color-primary)",
          fontSize: "0.95rem", fontWeight: 700,
          cursor: "pointer", fontFamily: "inherit",
          transition: "all 0.2s",
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.borderColor = "var(--color-primary)";
          e.currentTarget.style.backgroundColor = "var(--color-primary-light)";
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.borderColor = "var(--color-border)";
          e.currentTarget.style.backgroundColor = "transparent";
        }}
      >
        <UserPlus size={18} /> {t("welcome.createNew")}
      </button>
    </div>
  );
}
