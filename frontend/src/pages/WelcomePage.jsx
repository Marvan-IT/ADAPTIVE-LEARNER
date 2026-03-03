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
import GameBackground from "../components/game/GameBackground";
import LevelBadge from "../components/game/LevelBadge";
import StreakMeter from "../components/game/StreakMeter";

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
        <div style={{ textAlign: "center" }}>
          <div style={{
            width: "48px", height: "48px", margin: "0 auto 1rem",
            borderRadius: "50%",
            border: "3px solid var(--color-primary)",
            borderTopColor: "transparent",
            animation: "spin 0.8s linear infinite",
          }} aria-hidden="true" />
          <p style={{ color: "var(--color-text-muted)" }}>{t("common.loading")}</p>
        </div>
      </div>
    );
  }

  return (
    <div style={{
      minHeight: "100vh",
      background: "linear-gradient(135deg, var(--color-bg) 0%, color-mix(in srgb, var(--color-primary) 8%, var(--color-bg)) 100%)",
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      justifyContent: "center",
      padding: "2rem 1.5rem",
      position: "relative",
    }}>
      <GameBackground />

      {/* Language Selector — top right */}
      <div style={{ position: "absolute", top: "1.5rem", right: "1.5rem", zIndex: 1 }}>
        <LanguageSelector />
      </div>

      {/* Decorative blobs */}
      <div aria-hidden="true" style={{
        position: "absolute", top: "-80px", left: "-80px",
        width: "320px", height: "320px",
        borderRadius: "50%",
        background: "radial-gradient(circle, color-mix(in srgb, var(--color-primary) 15%, transparent), transparent 70%)",
        pointerEvents: "none",
      }} />
      <div aria-hidden="true" style={{
        position: "absolute", bottom: "-60px", right: "-60px",
        width: "240px", height: "240px",
        borderRadius: "50%",
        background: "radial-gradient(circle, color-mix(in srgb, var(--color-accent) 12%, transparent), transparent 70%)",
        pointerEvents: "none",
      }} />

      {/* Hero */}
      <div
        className="fade-up"
        style={{ textAlign: "center", marginBottom: "2.5rem", position: "relative", zIndex: 1 }}
      >
        <div style={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          width: "96px",
          height: "96px",
          borderRadius: "50%",
          background: "linear-gradient(135deg, var(--color-primary), var(--color-accent))",
          marginBottom: "1.25rem",
          animation: "pulse-glow 2.5s infinite",
          boxShadow: "var(--shadow-xl)",
        }}>
          <Brain size={48} color="#fff" aria-hidden="true" />
        </div>
        <h1 style={{
          fontSize: "3.25rem",
          fontWeight: 800,
          color: "var(--color-text)",
          marginBottom: "0.5rem",
          lineHeight: 1.1,
          letterSpacing: "-0.02em",
        }}>
          {t("app.title")}
        </h1>
        <p style={{
          fontSize: "1.2rem",
          color: "var(--color-text-muted)",
          maxWidth: "380px",
          margin: "0 auto",
          lineHeight: 1.6,
        }}>
          {t("app.tagline")}
        </p>
      </div>

      {/* Player profile strip — shown when a student is already loaded */}
      {student && (
        <div className="fade-up" style={{
          display: "flex", alignItems: "center", gap: "0.75rem",
          padding: "0.6rem 1.2rem",
          borderRadius: "var(--radius-full)",
          background: "color-mix(in srgb, var(--color-surface) 80%, transparent)",
          backdropFilter: "blur(8px)",
          WebkitBackdropFilter: "blur(8px)",
          border: "1px solid color-mix(in srgb, var(--color-border) 50%, transparent)",
          marginBottom: "1rem",
          animationDelay: "60ms",
          position: "relative", zIndex: 1,
        }}>
          <div style={{
            width: "32px", height: "32px", borderRadius: "50%",
            background: "linear-gradient(135deg, var(--color-primary), var(--color-accent))",
            display: "flex", alignItems: "center", justifyContent: "center",
            color: "#fff", fontWeight: 800, fontSize: "0.9rem",
            flexShrink: 0,
          }}>
            {(student.display_name || "S")[0].toUpperCase()}
          </div>
          <LevelBadge size={28} />
          <StreakMeter compact />
          <span style={{ fontSize: "0.8rem", color: "var(--color-text-muted)", fontWeight: 600 }}>
            {student.display_name}
          </span>
        </div>
      )}

      {/* Glassmorphism Card */}
      <div
        className="fade-up float-card"
        style={{
          backdropFilter: "blur(12px)",
          WebkitBackdropFilter: "blur(12px)",
          backgroundColor: "color-mix(in srgb, var(--color-surface) 85%, transparent)",
          borderRadius: "var(--radius-xl)",
          padding: "2.25rem",
          width: "100%",
          maxWidth: "500px",
          border: "1.5px solid color-mix(in srgb, var(--color-border) 60%, transparent)",
          boxShadow: "var(--shadow-xl)",
          animationDelay: "80ms",
          position: "relative",
          zIndex: 1,
        }}
      >
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
