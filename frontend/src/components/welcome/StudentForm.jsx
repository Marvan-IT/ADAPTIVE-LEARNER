import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useStudent } from "../../context/StudentContext";
import { useTheme } from "../../context/ThemeContext";
import { createStudent } from "../../api/students";
import { SUGGESTED_INTERESTS, STYLES } from "../../utils/constants";
import { trackEvent } from "../../utils/analytics";
import { BookOpen, Skull, Rocket, Gamepad2, X, Plus, ArrowLeft } from "lucide-react";

const STYLE_ICONS = { default: BookOpen, pirate: Skull, astronaut: Rocket, gamer: Gamepad2 };

export default function StudentForm({ onBack }) {
  const { t, i18n } = useTranslation();
  const [name, setName] = useState("");
  const [interests, setInterests] = useState([]);
  const [selectedStyle, setSelectedStyle] = useState("default");
  const [interestInput, setInterestInput] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const { setStudent } = useStudent();
  const { setStyle } = useTheme();
  const navigate = useNavigate();

  useEffect(() => {
    trackEvent("student_form_viewed");
  }, []);

  const addInterest = (interest) => {
    const trimmed = interest.trim().toLowerCase();
    if (trimmed && !interests.includes(trimmed) && interests.length < 10) {
      setInterests([...interests, trimmed]);
    }
    setInterestInput("");
  };

  const removeInterest = (interest) => {
    setInterests(interests.filter((i) => i !== interest));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!name.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await createStudent(name.trim(), interests, selectedStyle, i18n.language);
      setStudent(res.data);
      setStyle(selectedStyle);
      trackEvent("student_created", {
        student_id: res.data.id,
        student_name: res.data.display_name,
        interests: interests,
        interests_count: interests.length,
        style: selectedStyle,
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
            trackEvent("student_form_abandoned", { interests_count: interests.length, style: selectedStyle });
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

      {/* Interests */}
      <div style={{ marginBottom: "1rem" }}>
        <span style={{ fontSize: "0.85rem", fontWeight: 500, color: "var(--color-text-muted)" }}>
          {t("form.interestsLabel")}
          <span style={{ marginLeft: "0.35rem", fontSize: "0.78rem", fontWeight: 400 }}>
            ({t("form.optional", "optional")})
          </span>
        </span>
        {/* Tags */}
        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem", marginTop: "0.5rem" }}>
          {interests.map((i) => (
            <span
              key={i}
              style={{
                display: "flex", alignItems: "center", gap: "0.3rem",
                padding: "0.3rem 0.7rem", borderRadius: "20px",
                backgroundColor: "var(--color-primary-light)", color: "var(--color-primary)",
                fontSize: "0.85rem", fontWeight: 600,
              }}
            >
              {t("interest." + i, i)}
              <X size={14} style={{ cursor: "pointer" }} onClick={() => removeInterest(i)} />
            </span>
          ))}
        </div>
        {/* Input */}
        <div style={{ display: "flex", gap: "0.4rem", marginTop: "0.5rem" }}>
          <input
            type="text"
            value={interestInput}
            onChange={(e) => setInterestInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") { e.preventDefault(); addInterest(interestInput); }
            }}
            placeholder={t("form.interestsPlaceholder")}
            style={{
              flex: 1, padding: "0.5rem 0.8rem", fontSize: "0.95rem",
              borderRadius: "10px", border: "2px solid var(--color-border)",
              backgroundColor: "var(--color-bg)", color: "var(--color-text)",
              fontFamily: "inherit", outline: "none",
            }}
          />
          <button
            type="button"
            onClick={() => addInterest(interestInput)}
            style={{
              display: "flex", alignItems: "center", padding: "0.5rem",
              borderRadius: "10px", border: "2px solid var(--color-primary)",
              backgroundColor: "var(--color-primary)", color: "#fff",
              cursor: "pointer",
            }}
          >
            <Plus size={18} />
          </button>
        </div>
        {/* Suggestions */}
        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.3rem", marginTop: "0.5rem" }}>
          {SUGGESTED_INTERESTS.filter((s) => !interests.includes(s)).slice(0, 6).map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => addInterest(s)}
              style={{
                padding: "0.25rem 0.6rem", borderRadius: "15px",
                border: "1px solid var(--color-border)", backgroundColor: "transparent",
                color: "var(--color-text-muted)", fontSize: "0.8rem",
                cursor: "pointer", fontFamily: "inherit",
              }}
            >
              + {t("interest." + s, s)}
            </button>
          ))}
        </div>
      </div>

      {/* Style Picker */}
      <div style={{ marginBottom: "1.5rem" }}>
        <span style={{ fontSize: "0.95rem", fontWeight: 600, color: "var(--color-text)" }}>
          {t("form.styleLabel")}
        </span>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.5rem", marginTop: "0.5rem" }}>
          {STYLES.map(({ id, label, description }) => {
            const Icon = STYLE_ICONS[id];
            const active = selectedStyle === id;
            return (
              <button
                key={id}
                type="button"
                onClick={() => setSelectedStyle(id)}
                style={{
                  display: "flex", alignItems: "center", gap: "0.5rem",
                  padding: "0.7rem", borderRadius: "10px",
                  border: active ? "2px solid var(--color-primary)" : "2px solid var(--color-border)",
                  backgroundColor: active ? "var(--color-primary-light)" : "transparent",
                  color: active ? "var(--color-primary)" : "var(--color-text)",
                  cursor: "pointer", fontFamily: "inherit", textAlign: "left",
                  transition: "all 0.2s",
                }}
              >
                <Icon size={20} />
                <div>
                  <div style={{ fontWeight: 700, fontSize: "0.9rem" }}>{t("style." + id)}</div>
                  <div style={{ fontSize: "0.75rem", color: "var(--color-text-muted)" }}>{description}</div>
                </div>
              </button>
            );
          })}
        </div>
      </div>

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
          backgroundColor: name.trim() ? "var(--color-primary)" : "var(--color-border)",
          color: name.trim() ? "#fff" : "var(--color-text-muted)",
          fontSize: "1.1rem", fontWeight: 700,
          cursor: name.trim() ? "pointer" : "not-allowed",
          fontFamily: "inherit",
          transition: "all 0.2s",
        }}
      >
        {submitting ? t("form.submitting") : t("form.submit")}
      </button>
    </form>
  );
}
