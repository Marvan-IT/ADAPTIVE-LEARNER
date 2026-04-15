import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useStudent } from "../../context/StudentContext";
import { useTheme } from "../../context/ThemeContext";
import { createStudent } from "../../api/students";
import { trackEvent } from "../../utils/analytics";
import { ArrowLeft } from "lucide-react";

export default function StudentForm({ onBack }) {
  const { t, i18n } = useTranslation();
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const { setStudent } = useStudent();
  const { setStyle } = useTheme();
  const navigate = useNavigate();

  useEffect(() => {
    trackEvent("student_form_viewed");
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!name.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await createStudent(name.trim(), [], "default", i18n.language);
      setStudent(res.data);
      setStyle("default");
      trackEvent("student_created", {
        student_id: res.data.id,
        student_name: res.data.display_name,
        interests: [],
        interests_count: 0,
        style: "default",
        preferred_language: i18n.language,
      });
      navigate("/map");
    } catch (err) {
      const msg = err.response?.data?.detail || t("form.error");
      trackEvent("student_creation_failed", { error: msg });
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit}>
      {onBack && (
        <button
          type="button"
          onClick={() => {
            trackEvent("student_form_abandoned", { interests_count: 0, style: "default" });
            onBack();
          }}
          style={{
            display: "flex", alignItems: "center", gap: "0.3rem",
            background: "none", border: "none", color: "var(--color-text-muted)",
            cursor: "pointer", fontFamily: "inherit", fontSize: "0.9rem", marginBottom: "1rem",
          }}
        >
          <ArrowLeft size={16} /> {t("common.back")}
        </button>
      )}

      <h2 style={{ fontSize: "1.4rem", fontWeight: 700, color: "var(--color-text)", marginBottom: "1.5rem" }}>
        {t("form.createProfile")}
      </h2>

      {/* Name */}
      <label style={{ display: "block", marginBottom: "1rem" }}>
        <span style={{ fontSize: "0.95rem", fontWeight: 600, color: "var(--color-text)" }}>
          {t("form.nameLabel")}
        </span>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t("form.namePlaceholder")}
          maxLength={100}
          required
          style={{
            display: "block", width: "100%", marginTop: "0.4rem",
            padding: "0.7rem 1rem", fontSize: "1.1rem",
            borderRadius: "10px", border: "2px solid var(--color-border)",
            backgroundColor: "var(--color-bg)", color: "var(--color-text)",
            fontFamily: "inherit", outline: "none",
            transition: "border-color 0.2s",
          }}
          onFocus={(e) => (e.target.style.borderColor = "var(--color-primary)")}
          onBlur={(e) => (e.target.style.borderColor = "var(--color-border)")}
        />
      </label>

      <p style={{ fontSize: 12, color: '#888', marginTop: 8 }}>
        {t('studentForm.customizeNote')}
      </p>

      {/* Error */}
      {error && (
        <p style={{ color: "var(--color-danger)", fontSize: "0.9rem", marginBottom: "1rem" }}>
          {error}
        </p>
      )}

      {/* Submit */}
      <button
        type="submit"
        disabled={!name.trim() || submitting}
        style={{
          width: "100%", padding: "0.8rem",
          borderRadius: "12px", border: "none",
          backgroundColor: name.trim() ? "var(--color-primary-dark)" : "var(--color-border)",
          color: name.trim() ? "#fff" : "var(--color-text-muted)",
          fontSize: "1.1rem", fontWeight: 700,
          cursor: name.trim() ? "pointer" : "not-allowed",
          fontFamily: "inherit",
          transition: "all 0.2s",
          marginTop: "1.5rem",
        }}
      >
        {submitting ? t("form.submitting") : t("form.submit")}
      </button>
    </form>
  );
}
