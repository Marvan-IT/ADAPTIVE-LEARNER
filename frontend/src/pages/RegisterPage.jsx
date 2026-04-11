import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { motion, AnimatePresence } from "framer-motion";
import { Brain, User, Mail, Lock, AlertCircle, X } from "lucide-react";
import { registerUser } from "../api/auth";

const PALETTE = {
  bg: "#0f0a1a",
  card: "#1a1025",
  accent: "#7c3aed",
  accentHover: "#6d28d9",
  text: "#e2e8f0",
  muted: "#94a3b8",
  inputBg: "#2d1f3d",
  inputBorder: "#4c3a6e",
  inputBorderFocus: "#7c3aed",
  error: "#ef4444",
  errorBg: "rgba(239,68,68,0.08)",
  success: "#22c55e",
  tag: "rgba(124,58,237,0.15)",
  tagBorder: "rgba(124,58,237,0.3)",
};

const SUPPORTED_LANGUAGES = [
  { code: "en", label: "English" },
  { code: "ar", label: "Arabic" },
  { code: "de", label: "German" },
  { code: "es", label: "Spanish" },
  { code: "fr", label: "French" },
  { code: "hi", label: "Hindi" },
  { code: "ja", label: "Japanese" },
  { code: "ko", label: "Korean" },
  { code: "ml", label: "Malayalam" },
  { code: "pt", label: "Portuguese" },
  { code: "si", label: "Sinhala" },
  { code: "ta", label: "Tamil" },
  { code: "zh", label: "Chinese" },
];

const STYLES = [
  { id: "default", emoji: "📚", label: "Default" },
  { id: "pirate", emoji: "🏴‍☠️", label: "Pirate" },
  { id: "astronaut", emoji: "🚀", label: "Space" },
  { id: "gamer", emoji: "🎮", label: "Gamer" },
];

function passwordStrength(pw) {
  if (!pw) return { score: 0, label: "", color: "transparent" };
  let score = 0;
  if (pw.length >= 8) score++;
  if (/[A-Z]/.test(pw)) score++;
  if (/[0-9]/.test(pw)) score++;
  if (/[^A-Za-z0-9]/.test(pw)) score++;
  const labels = ["", "Weak", "Fair", "Good", "Strong"];
  const colors = ["transparent", "#ef4444", "#f59e0b", "#3b82f6", "#22c55e"];
  return { score, label: labels[score], color: colors[score] };
}

function StrengthBar({ password }) {
  const { score, label, color } = passwordStrength(password);
  if (!password) return null;
  return (
    <div style={{ marginTop: "0.5rem" }}>
      <div
        style={{
          display: "flex",
          gap: "4px",
          marginBottom: "4px",
        }}
      >
        {[1, 2, 3, 4].map((i) => (
          <div
            key={i}
            style={{
              flex: 1,
              height: "3px",
              borderRadius: "2px",
              background: i <= score ? color : "rgba(255,255,255,0.1)",
              transition: "background 0.2s",
            }}
          />
        ))}
      </div>
      <span style={{ fontSize: "0.75rem", color }}>{label}</span>
    </div>
  );
}

function InputField({
  id,
  label,
  type = "text",
  value,
  onChange,
  placeholder,
  autoComplete,
  icon: Icon,
  focusedField,
  onFocus,
  onBlur,
  required,
  children,
}) {
  return (
    <div style={{ marginBottom: "1.1rem" }}>
      <label
        htmlFor={id}
        style={{
          display: "block",
          color: PALETTE.muted,
          fontSize: "0.8rem",
          fontWeight: 600,
          letterSpacing: "0.04em",
          textTransform: "uppercase",
          marginBottom: "0.5rem",
        }}
      >
        {label}
      </label>
      <div style={{ position: "relative" }}>
        {Icon && (
          <Icon
            size={16}
            color={focusedField === id ? "#a78bfa" : PALETTE.inputBorder}
            aria-hidden="true"
            style={{
              position: "absolute",
              left: "14px",
              top: "50%",
              transform: "translateY(-50%)",
              pointerEvents: "none",
              transition: "color 0.15s",
            }}
          />
        )}
        <input
          id={id}
          type={type}
          autoComplete={autoComplete}
          value={value}
          onChange={onChange}
          onFocus={onFocus}
          onBlur={onBlur}
          placeholder={placeholder}
          required={required}
          style={{
            width: "100%",
            boxSizing: "border-box",
            padding: `0.75rem 0.875rem 0.75rem ${Icon ? "2.5rem" : "0.875rem"}`,
            background: PALETTE.inputBg,
            border: `1px solid ${
              focusedField === id ? PALETTE.inputBorderFocus : PALETTE.inputBorder
            }`,
            borderRadius: "10px",
            color: PALETTE.text,
            fontSize: "0.95rem",
            outline: "none",
            transition: "border-color 0.15s",
          }}
        />
      </div>
      {children}
    </div>
  );
}

export default function RegisterPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [interests, setInterests] = useState([]);
  const [interestInput, setInterestInput] = useState("");
  const [preferredStyle, setPreferredStyle] = useState("default");
  const [preferredLanguage, setPreferredLanguage] = useState("en");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [focusedField, setFocusedField] = useState(null);

  const addInterest = (val) => {
    const trimmed = val.trim().toLowerCase();
    if (trimmed && !interests.includes(trimmed) && interests.length < 10) {
      setInterests((prev) => [...prev, trimmed]);
    }
    setInterestInput("");
  };

  const removeInterest = (tag) =>
    setInterests((prev) => prev.filter((i) => i !== tag));

  const handleInterestKeyDown = (e) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      addInterest(interestInput);
    } else if (e.key === "Backspace" && !interestInput && interests.length) {
      removeInterest(interests[interests.length - 1]);
    }
  };

  const validateForm = () => {
    if (!displayName.trim()) return t("auth.errorNameRequired", "Display name is required.");
    if (!email.trim()) return t("auth.errorEmailRequired", "Email is required.");
    if (!password) return t("auth.errorPasswordRequired", "Password is required.");
    if (password.length < 8) return t("auth.errorPasswordShort", "Password must be at least 8 characters.");
    if (password !== confirmPassword)
      return t("auth.errorPasswordMismatch", "Passwords do not match.");
    return null;
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const validationError = validateForm();
    if (validationError) { setError(validationError); return; }
    setError("");
    setLoading(true);
    try {
      await registerUser({
        display_name: displayName.trim(),
        email: email.trim(),
        password,
        interests,
        preferred_style: preferredStyle,
        preferred_language: preferredLanguage,
      });
      navigate("/verify-otp", {
        state: { email: email.trim(), purpose: "email_verify" },
      });
    } catch (err) {
      const detail = err.response?.data?.detail;
      if (typeof detail === "string") {
        setError(detail);
      } else if (Array.isArray(detail)) {
        setError(detail[0]?.msg || t("common.error", "Something went wrong"));
      } else {
        setError(t("auth.registerError", "Could not create account. Please try again."));
      }
    } finally {
      setLoading(false);
    }
  };

  const strength = passwordStrength(password);

  return (
    <div
      style={{
        minHeight: "100vh",
        background: PALETTE.bg,
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "center",
        padding: "2rem 1rem",
        fontFamily: "Inter, system-ui, sans-serif",
        overflowY: "auto",
      }}
    >
      {/* Background glow */}
      <div
        aria-hidden="true"
        style={{
          position: "fixed",
          top: "20%",
          left: "50%",
          transform: "translate(-50%, -50%)",
          width: "600px",
          height: "600px",
          background:
            "radial-gradient(circle at 50% 50%, rgba(124,58,237,0.1), transparent 65%)",
          pointerEvents: "none",
          zIndex: 0,
        }}
      />

      <motion.div
        initial={{ opacity: 0, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, ease: "easeOut" }}
        style={{
          position: "relative",
          zIndex: 1,
          width: "100%",
          maxWidth: "460px",
        }}
      >
        {/* Branding */}
        <div style={{ textAlign: "center", marginBottom: "1.75rem" }}>
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              width: "52px",
              height: "52px",
              borderRadius: "14px",
              background: "rgba(124,58,237,0.15)",
              border: "1px solid rgba(124,58,237,0.3)",
              marginBottom: "0.875rem",
            }}
          >
            <Brain size={26} color="#a78bfa" aria-hidden="true" />
          </div>
          <h1
            style={{
              fontSize: "1.65rem",
              fontWeight: 800,
              color: PALETTE.text,
              letterSpacing: "-0.02em",
              margin: 0,
              marginBottom: "0.3rem",
            }}
          >
            {t("auth.createAccountTitle", "Create your account")}
          </h1>
          <p style={{ color: PALETTE.muted, fontSize: "0.875rem", margin: 0 }}>
            {t("auth.registerSubtitle", "Start your learning journey today")}
          </p>
        </div>

        {/* Card */}
        <div
          style={{
            background: PALETTE.card,
            borderRadius: "20px",
            border: "1px solid rgba(124,58,237,0.18)",
            padding: "2rem",
            boxShadow:
              "0 4px 6px rgba(0,0,0,0.3), 0 0 0 1px rgba(255,255,255,0.03)",
          }}
        >
          {/* Error */}
          <AnimatePresence>
            {error && (
              <motion.div
                key="error"
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                style={{
                  background: PALETTE.errorBg,
                  border: `1px solid ${PALETTE.error}40`,
                  borderRadius: "10px",
                  padding: "0.75rem 1rem",
                  marginBottom: "1.25rem",
                  display: "flex",
                  alignItems: "center",
                  gap: "0.5rem",
                  color: PALETTE.error,
                  fontSize: "0.875rem",
                }}
                role="alert"
              >
                <AlertCircle size={16} aria-hidden="true" />
                {error}
              </motion.div>
            )}
          </AnimatePresence>

          <form onSubmit={handleSubmit} noValidate>
            <InputField
              id="reg-name"
              label={t("auth.displayNameLabel", "Display Name")}
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder={t("auth.displayNamePlaceholder", "Your name")}
              autoComplete="name"
              icon={User}
              focusedField={focusedField}
              onFocus={() => setFocusedField("reg-name")}
              onBlur={() => setFocusedField(null)}
              required
            />

            <InputField
              id="reg-email"
              label={t("auth.emailLabel", "Email")}
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder={t("auth.emailPlaceholder", "you@example.com")}
              autoComplete="email"
              icon={Mail}
              focusedField={focusedField}
              onFocus={() => setFocusedField("reg-email")}
              onBlur={() => setFocusedField(null)}
              required
            />

            <InputField
              id="reg-password"
              label={t("auth.passwordLabel", "Password")}
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              autoComplete="new-password"
              icon={Lock}
              focusedField={focusedField}
              onFocus={() => setFocusedField("reg-password")}
              onBlur={() => setFocusedField(null)}
              required
            >
              <StrengthBar password={password} />
            </InputField>

            <InputField
              id="reg-confirm"
              label={t("auth.confirmPasswordLabel", "Confirm Password")}
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="••••••••"
              autoComplete="new-password"
              icon={Lock}
              focusedField={focusedField}
              onFocus={() => setFocusedField("reg-confirm")}
              onBlur={() => setFocusedField(null)}
              required
            >
              {confirmPassword && password !== confirmPassword && (
                <p
                  style={{
                    color: PALETTE.error,
                    fontSize: "0.78rem",
                    marginTop: "4px",
                  }}
                >
                  {t("auth.passwordMismatchHint", "Passwords do not match")}
                </p>
              )}
            </InputField>

            {/* Interests */}
            <div style={{ marginBottom: "1.1rem" }}>
              <label
                htmlFor="reg-interests"
                style={{
                  display: "block",
                  color: PALETTE.muted,
                  fontSize: "0.8rem",
                  fontWeight: 600,
                  letterSpacing: "0.04em",
                  textTransform: "uppercase",
                  marginBottom: "0.5rem",
                }}
              >
                {t("form.interestsLabel", "Interests")}{" "}
                <span style={{ fontWeight: 400, textTransform: "none", fontSize: "0.75rem" }}>
                  {t("auth.interestsOptional", "(optional)")}
                </span>
              </label>
              <div
                style={{
                  display: "flex",
                  flexWrap: "wrap",
                  gap: "6px",
                  padding: "0.5rem",
                  background: PALETTE.inputBg,
                  border: `1px solid ${
                    focusedField === "reg-interests"
                      ? PALETTE.inputBorderFocus
                      : PALETTE.inputBorder
                  }`,
                  borderRadius: "10px",
                  transition: "border-color 0.15s",
                  minHeight: "44px",
                  alignItems: "center",
                }}
              >
                {interests.map((tag) => (
                  <span
                    key={tag}
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: "4px",
                      background: PALETTE.tag,
                      border: `1px solid ${PALETTE.tagBorder}`,
                      borderRadius: "6px",
                      padding: "2px 8px",
                      color: "#c4b5fd",
                      fontSize: "0.82rem",
                      fontWeight: 500,
                    }}
                  >
                    {tag}
                    <button
                      type="button"
                      onClick={() => removeInterest(tag)}
                      aria-label={`Remove ${tag}`}
                      style={{
                        background: "none",
                        border: "none",
                        cursor: "pointer",
                        color: "#a78bfa",
                        padding: 0,
                        display: "inline-flex",
                        alignItems: "center",
                      }}
                    >
                      <X size={12} aria-hidden="true" />
                    </button>
                  </span>
                ))}
                <input
                  id="reg-interests"
                  value={interestInput}
                  onChange={(e) => setInterestInput(e.target.value)}
                  onKeyDown={handleInterestKeyDown}
                  onBlur={() => {
                    if (interestInput.trim()) addInterest(interestInput);
                    setFocusedField(null);
                  }}
                  onFocus={() => setFocusedField("reg-interests")}
                  placeholder={
                    interests.length === 0
                      ? t("form.interestsPlaceholder", "space, music, games...")
                      : ""
                  }
                  style={{
                    flex: 1,
                    minWidth: "100px",
                    background: "transparent",
                    border: "none",
                    outline: "none",
                    color: PALETTE.text,
                    fontSize: "0.9rem",
                    padding: "2px 4px",
                  }}
                />
              </div>
              <p
                style={{
                  color: PALETTE.muted,
                  fontSize: "0.75rem",
                  marginTop: "4px",
                }}
              >
                {t("auth.interestsHint", "Press Enter or comma to add")}
              </p>
            </div>

            {/* Learning style */}
            <div style={{ marginBottom: "1.1rem" }}>
              <label
                style={{
                  display: "block",
                  color: PALETTE.muted,
                  fontSize: "0.8rem",
                  fontWeight: 600,
                  letterSpacing: "0.04em",
                  textTransform: "uppercase",
                  marginBottom: "0.5rem",
                }}
              >
                {t("form.styleLabel", "Tutor Style")}
              </label>
              <div style={{ display: "flex", gap: "8px" }}>
                {STYLES.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => setPreferredStyle(s.id)}
                    aria-label={t("aria.styleOption", { style: s.label })}
                    style={{
                      flex: 1,
                      padding: "0.6rem 0.25rem",
                      borderRadius: "10px",
                      border: `1px solid ${
                        preferredStyle === s.id
                          ? PALETTE.accent
                          : PALETTE.inputBorder
                      }`,
                      background:
                        preferredStyle === s.id
                          ? "rgba(124,58,237,0.18)"
                          : PALETTE.inputBg,
                      color: preferredStyle === s.id ? "#c4b5fd" : PALETTE.muted,
                      cursor: "pointer",
                      transition: "all 0.15s",
                      display: "flex",
                      flexDirection: "column",
                      alignItems: "center",
                      gap: "4px",
                      fontSize: "0.8rem",
                      fontWeight: preferredStyle === s.id ? 600 : 400,
                    }}
                  >
                    <span style={{ fontSize: "1.2rem" }}>{s.emoji}</span>
                    {s.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Language */}
            <div style={{ marginBottom: "1.5rem" }}>
              <label
                htmlFor="reg-language"
                style={{
                  display: "block",
                  color: PALETTE.muted,
                  fontSize: "0.8rem",
                  fontWeight: 600,
                  letterSpacing: "0.04em",
                  textTransform: "uppercase",
                  marginBottom: "0.5rem",
                }}
              >
                {t("form.languageLabel", "Preferred Language")}
              </label>
              <select
                id="reg-language"
                value={preferredLanguage}
                onChange={(e) => setPreferredLanguage(e.target.value)}
                style={{
                  width: "100%",
                  padding: "0.75rem 0.875rem",
                  background: PALETTE.inputBg,
                  border: `1px solid ${PALETTE.inputBorder}`,
                  borderRadius: "10px",
                  color: PALETTE.text,
                  fontSize: "0.95rem",
                  outline: "none",
                  cursor: "pointer",
                  appearance: "none",
                  WebkitAppearance: "none",
                }}
              >
                {SUPPORTED_LANGUAGES.map((lang) => (
                  <option
                    key={lang.code}
                    value={lang.code}
                    style={{ background: PALETTE.card }}
                  >
                    {lang.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Submit */}
            <button
              type="submit"
              disabled={loading || strength.score < 2 || password !== confirmPassword || !displayName.trim() || !email.trim()}
              style={{
                width: "100%",
                padding: "0.875rem",
                background:
                  loading || strength.score < 2 || password !== confirmPassword || !displayName.trim() || !email.trim()
                    ? "rgba(124,58,237,0.4)"
                    : PALETTE.accent,
                color: "#fff",
                border: "none",
                borderRadius: "10px",
                fontSize: "0.95rem",
                fontWeight: 700,
                cursor:
                  loading || strength.score < 2 || password !== confirmPassword || !displayName.trim() || !email.trim()
                    ? "not-allowed"
                    : "pointer",
                transition: "background 0.15s",
                letterSpacing: "0.01em",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: "0.5rem",
              }}
              onMouseEnter={(e) => {
                if (!loading) e.currentTarget.style.background = PALETTE.accentHover;
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background =
                  loading || strength.score < 2 || password !== confirmPassword || !displayName.trim() || !email.trim()
                    ? "rgba(124,58,237,0.4)"
                    : PALETTE.accent;
              }}
            >
              {loading ? (
                <>
                  <div
                    style={{
                      width: "16px",
                      height: "16px",
                      border: "2px solid rgba(255,255,255,0.3)",
                      borderTopColor: "#fff",
                      borderRadius: "50%",
                      animation: "spin 0.7s linear infinite",
                    }}
                    aria-hidden="true"
                  />
                  {t("form.submitting", "Creating...")}
                </>
              ) : (
                t("auth.signUpButton", "Sign Up")
              )}
            </button>
          </form>
        </div>

        {/* Login link */}
        <p
          style={{
            textAlign: "center",
            color: PALETTE.muted,
            fontSize: "0.9rem",
            marginTop: "1.5rem",
            paddingBottom: "2rem",
          }}
        >
          {t("auth.haveAccount", "Already have an account?")}{" "}
          <Link
            to="/login"
            style={{
              color: "#a78bfa",
              fontWeight: 600,
              textDecoration: "none",
            }}
          >
            {t("auth.signIn", "Sign In")}
          </Link>
        </p>
      </motion.div>
    </div>
  );
}
