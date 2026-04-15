import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { AnimatePresence, motion } from "framer-motion";
import { useStudent } from "../context/StudentContext";
import { trackEvent } from "../utils/analytics";
import StudentForm from "../components/welcome/StudentForm";
import StudentCard from "../components/welcome/StudentCard";
import StudentPicker from "../components/welcome/StudentPicker";
import LanguageSelector from "../components/LanguageSelector";
import { Brain, Sparkles, BookOpen, Globe2 } from "lucide-react";

const featurePillStyle = {
  background: "rgba(99,102,241,0.12)",
  border: "1px solid rgba(99,102,241,0.25)",
  borderRadius: "9999px",
  padding: "0.3rem 0.75rem",
  color: "#a5b4fc",
  fontWeight: 600,
  fontSize: "0.8rem",
  display: "flex",
  alignItems: "center",
  gap: "6px",
};

export default function WelcomePage() {
  const { t } = useTranslation();
  const { student, loading } = useStudent();
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

  const viewKey = student && !showForm ? "card" : showForm ? "form" : "picker";

  return (
    <div style={{
      display: "flex",
      minHeight: "100vh",
      overflow: "hidden",
    }}>
      {/* Left Panel */}
      <div style={{
        width: "50%",
        background: "linear-gradient(160deg, #0c0c16, #18143a)",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "3rem 3.5rem",
        position: "relative",
        overflow: "hidden",
      }}>
        {/* Language Selector — absolute top-right of left panel */}
        <div style={{ position: "absolute", top: "1.5rem", right: "1.5rem", zIndex: 2 }}>
          <LanguageSelector />
        </div>

        {/* Radial glow behind brain */}
        <div aria-hidden="true" style={{
          position: "absolute",
          top: "50%",
          left: "50%",
          transform: "translate(-50%, -50%)",
          width: "300px",
          height: "300px",
          background: "radial-gradient(circle at 50% 50%, rgba(99,102,241,0.3), transparent 60%)",
          pointerEvents: "none",
          zIndex: 0,
        }} />

        {/* Content */}
        <div style={{ position: "relative", zIndex: 1, maxWidth: "380px", width: "100%" }}>
          {/* Brain icon */}
          <div style={{
            width: "72px",
            height: "72px",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            marginBottom: "1.75rem",
            animation: "pulse-glow 2.5s infinite",
          }}>
            <Brain size={72} color="var(--color-primary)" aria-hidden="true" />
          </div>

          {/* App title */}
          <h1 style={{
            fontSize: "4rem",
            fontWeight: 800,
            fontFamily: "Inter, sans-serif",
            lineHeight: 1,
            letterSpacing: "-0.03em",
            marginBottom: "1rem",
            background: "linear-gradient(135deg, var(--color-primary), var(--color-primary-dark))",
            WebkitBackgroundClip: "text",
            WebkitTextFillColor: "transparent",
            backgroundClip: "text",
          }}>
            {t("app.title", "Adaptive Learner")}
          </h1>

          {/* Tagline */}
          <p style={{
            fontSize: "1.1rem",
            color: "rgba(240,240,255,0.6)",
            maxWidth: "340px",
            lineHeight: 1.6,
            marginBottom: "2rem",
          }}>
            {t("app.tagline")}
          </p>

          {/* Feature pills */}
          <div style={{
            display: "flex",
            flexDirection: "row",
            gap: "8px",
            flexWrap: "wrap",
          }}>
            <div style={featurePillStyle}>
              <Sparkles size={14} aria-hidden="true" />
              {t("welcome.feature.adaptive", "Adaptive AI Tutor")}
            </div>
            <div style={featurePillStyle}>
              <BookOpen size={14} aria-hidden="true" />
              {t("welcome.feature.textbooks", "16 OpenStax Textbooks")}
            </div>
            <div style={featurePillStyle}>
              <Globe2 size={14} aria-hidden="true" />
              {t("welcome.feature.languages", "13 Languages")}
            </div>
          </div>
        </div>
      </div>

      {/* Right Panel */}
      <div style={{
        width: "50%",
        background: "var(--color-bg)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        overflow: "hidden",
      }}>
        <div style={{
          maxWidth: "420px",
          width: "100%",
          padding: "2.5rem",
        }}>
          <AnimatePresence mode="wait">
            <motion.div
              key={viewKey}
              initial={{ opacity: 0, x: 16 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -16 }}
              transition={{ duration: 0.2 }}
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
            </motion.div>
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}
