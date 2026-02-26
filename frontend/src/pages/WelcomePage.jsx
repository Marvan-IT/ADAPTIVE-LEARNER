import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useStudent } from "../context/StudentContext";
import { useTheme } from "../context/ThemeContext";
import { trackEvent } from "../utils/analytics";
import StudentForm from "../components/welcome/StudentForm";
import StudentCard from "../components/welcome/StudentCard";
import StudentPicker from "../components/welcome/StudentPicker";
import LanguageSelector from "../components/LanguageSelector";
import { Brain } from "lucide-react";

export default function WelcomePage() {
  const { t } = useTranslation();
  const { student, loading } = useStudent();
  const { style } = useTheme();
  const navigate = useNavigate();
  const [showForm, setShowForm] = useState(false);

  useEffect(() => {
    if (!loading) {
      trackEvent("welcome_page_viewed", { has_saved_student: !!student });
    }
  }, [loading, student]);

  if (loading) {
    return (
      <div style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        minHeight: "100vh",
        backgroundColor: "var(--color-bg)",
      }}>
        <p style={{ color: "var(--color-text-muted)", fontSize: "1.2rem" }}>{t("common.loading")}</p>
      </div>
    );
  }

  return (
    <div style={{
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      justifyContent: "center",
      minHeight: "100vh",
      padding: "2rem",
      backgroundColor: "var(--color-bg)",
      position: "relative",
    }}>
      {/* Language Selector — top right */}
      <div style={{ position: "absolute", top: "1.5rem", right: "1.5rem" }}>
        <LanguageSelector />
      </div>

      {/* Header */}
      <div style={{ textAlign: "center", marginBottom: "2rem" }}>
        <div style={{
          display: "inline-flex",
          alignItems: "center",
          gap: "0.5rem",
          marginBottom: "0.5rem",
        }}>
          <Brain size={48} color="var(--color-primary)" />
        </div>
        <h1 style={{
          fontSize: "2.5rem",
          fontWeight: 800,
          color: "var(--color-primary)",
          marginBottom: "0.3rem",
        }}>
          {t("app.title")}
        </h1>
        <p style={{
          fontSize: "1.2rem",
          color: "var(--color-text-muted)",
        }}>
          {t("app.tagline")}
        </p>
      </div>

      {/* Card */}
      <div style={{
        backgroundColor: "var(--color-surface)",
        borderRadius: "16px",
        padding: "2rem",
        width: "100%",
        maxWidth: "480px",
        border: "2px solid var(--color-border)",
        boxShadow: "0 4px 24px rgba(0,0,0,0.08)",
      }}>
        {student && !showForm ? (
          <StudentCard
            student={student}
            onContinue={() => navigate("/map")}
            onNewStudent={() => setShowForm(true)}
          />
        ) : showForm ? (
          <StudentForm onBack={() => setShowForm(false)} />
        ) : (
          <StudentPicker onCreateNew={() => setShowForm(true)} />
        )}
      </div>
    </div>
  );
}
