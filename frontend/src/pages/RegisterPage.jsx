import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { motion, AnimatePresence } from "framer-motion";
import { User, Mail, Lock, AlertCircle } from "lucide-react";
import { registerUser } from "../api/auth";
import { StrengthBar, passwordStrength } from "../components/ui";

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

// --- Style constants (compact for register page) ---
const compactInput = {
  width: "100%",
  height: 42,
  paddingLeft: 40,
  paddingRight: 14,
  background: "#F8FAFC",
  border: "1.5px solid #E2E8F0",
  borderRadius: 10,
  fontSize: 14,
  color: "#1E293B",
  outline: "none",
  transition: "border-color 0.2s, box-shadow 0.2s",
  boxSizing: "border-box",
};

const compactInputFocused = {
  ...compactInput,
  border: "1.5px solid #F97316",
  boxShadow: "0 0 0 3px rgba(249,115,22,0.12)",
};

const compactInputNoIcon = {
  ...compactInput,
  paddingLeft: 14,
};

const compactInputNoIconFocused = {
  ...compactInputFocused,
  paddingLeft: 14,
};

const compactSelectStyle = {
  ...compactInput,
  paddingLeft: 14,
  cursor: "pointer",
  appearance: "none",
  WebkitAppearance: "none",
};

const compactSelectFocused = {
  ...compactInputFocused,
  paddingLeft: 14,
  cursor: "pointer",
  appearance: "none",
  WebkitAppearance: "none",
};

const iconBase = {
  position: "absolute",
  left: 12,
  top: "50%",
  transform: "translateY(-50%)",
  pointerEvents: "none",
  color: "#94A3B8",
  transition: "color 0.2s",
};

const iconFocused = {
  ...iconBase,
  color: "#F97316",
};

const compactLabel = {
  display: "block",
  fontSize: 12,
  fontWeight: 600,
  color: "#64748B",
  marginBottom: 4,
};

const compactCard = {
  background: "#FFFFFF",
  borderRadius: 20,
  padding: "20px 20px",
  boxShadow: "0 4px 24px rgba(0,0,0,0.07)",
};

// --- InputField sub-component (inline styles) ---
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
  const isFocused = focusedField === id;
  return (
    <div style={{ marginBottom: 12 }}>
      <label htmlFor={id} style={compactLabel}>
        {label}
      </label>
      <div style={{ position: "relative" }}>
        {Icon && (
          <Icon
            size={15}
            style={isFocused ? iconFocused : iconBase}
            aria-hidden="true"
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
          style={isFocused ? compactInputFocused : compactInput}
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
  const [age, setAge] = useState("");
  const [preferredLanguage, setPreferredLanguage] = useState("en");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [focusedField, setFocusedField] = useState(null);

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
        age: age ? parseInt(age, 10) : null,
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
  const isDisabled =
    loading ||
    strength.score < 2 ||
    password !== confirmPassword ||
    !displayName.trim() ||
    !email.trim();

  const buttonStyle = {
    width: "100%",
    height: 42,
    background: !isDisabled ? "linear-gradient(135deg, #F97316, #EA580C)" : "#FDBA74",
    color: "#FFFFFF",
    border: "none",
    borderRadius: 9999,
    fontSize: 15,
    fontWeight: 700,
    cursor: !isDisabled ? "pointer" : "not-allowed",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    transition: "all 0.2s",
    marginTop: 4,
  };

  return (
    <>
      <div style={compactCard}>
        <h1
          style={{
            fontSize: 20,
            fontWeight: 800,
            color: "#1E293B",
            marginBottom: 4,
            marginTop: 0,
          }}
        >
          {t("auth.joinAdventure", "Join the adventure!")}
        </h1>
        <p
          style={{
            fontSize: 13,
            color: "#94A3B8",
            marginBottom: 12,
            marginTop: 0,
          }}
        >
          {t("auth.registerSubtitle", "Start your learning journey today")}
        </p>

        {/* Error banner */}
        <AnimatePresence>
          {error && (
            <motion.div
              key="error"
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              role="alert"
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                borderRadius: 12,
                padding: "10px 14px",
                marginBottom: 14,
                fontSize: 13,
                color: "#DC2626",
                background: "rgba(239,68,68,0.06)",
                border: "1px solid rgba(239,68,68,0.2)",
              }}
            >
              <AlertCircle size={15} aria-hidden="true" />
              {error}
            </motion.div>
          )}
        </AnimatePresence>

        <form onSubmit={handleSubmit} noValidate>
          {/* Display name */}
          <InputField
            id="reg-name"
            label={t("auth.displayNameLabel", "Display name")}
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

          {/* Email */}
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

          {/* Password */}
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

          {/* Confirm password */}
          <InputField
            id="reg-confirm"
            label={t("auth.confirmPasswordLabel", "Confirm password")}
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
                  color: "#DC2626",
                  fontSize: 12,
                  marginTop: 4,
                  marginBottom: 0,
                }}
              >
                {t("auth.passwordMismatchHint", "Passwords do not match")}
              </p>
            )}
          </InputField>

          {/* Age (optional) */}
          <div style={{ marginBottom: 12 }}>
            <label htmlFor="reg-age" style={compactLabel}>
              {t("auth.ageLabel", "Age")}{" "}
              <span style={{ fontWeight: 400, fontSize: 11, color: "#94A3B8" }}>
                {t("auth.ageOptional", "(optional)")}
              </span>
            </label>
            <input
              id="reg-age"
              type="number"
              min={5}
              max={120}
              value={age}
              onChange={(e) => setAge(e.target.value)}
              onFocus={() => setFocusedField("reg-age")}
              onBlur={() => setFocusedField(null)}
              placeholder={t("auth.agePlaceholder", "Your age")}
              style={
                focusedField === "reg-age"
                  ? compactInputNoIconFocused
                  : compactInputNoIcon
              }
            />
          </div>

          {/* Preferred language */}
          <div style={{ marginBottom: 16 }}>
            <label htmlFor="reg-language" style={compactLabel}>
              {t("form.languageLabel", "Preferred language")}
            </label>
            <div style={{ position: "relative" }}>
              <select
                id="reg-language"
                value={preferredLanguage}
                onChange={(e) => setPreferredLanguage(e.target.value)}
                onFocus={() => setFocusedField("reg-language")}
                onBlur={() => setFocusedField(null)}
                style={
                  focusedField === "reg-language"
                    ? compactSelectFocused
                    : compactSelectStyle
                }
              >
                {SUPPORTED_LANGUAGES.map((lang) => (
                  <option key={lang.code} value={lang.code}>
                    {lang.label}
                  </option>
                ))}
              </select>
              {/* Custom chevron for select */}
              <span
                style={{
                  position: "absolute",
                  right: 12,
                  top: "50%",
                  transform: "translateY(-50%)",
                  pointerEvents: "none",
                  color: "#94A3B8",
                  fontSize: 11,
                  lineHeight: 1,
                }}
                aria-hidden="true"
              >
                ▾
              </span>
            </div>
          </div>

          {/* Submit */}
          <motion.button
            type="submit"
            disabled={isDisabled}
            whileHover={!isDisabled ? { scale: 1.02 } : {}}
            whileTap={!isDisabled ? { scale: 0.97 } : {}}
            style={buttonStyle}
          >
            {loading ? (
              <span
                style={{
                  width: 16,
                  height: 16,
                  border: "2.5px solid rgba(255,255,255,0.35)",
                  borderTopColor: "#FFFFFF",
                  borderRadius: "50%",
                  display: "inline-block",
                  animation: "spin 0.7s linear infinite",
                }}
                aria-hidden="true"
              />
            ) : null}
            {loading ? t("auth.loggingIn", "Creating account...") : t("auth.signUpButton", "Sign Up")}
          </motion.button>
        </form>
      </div>

      {/* Login link */}
      <p
        style={{
          textAlign: "center",
          fontSize: 14,
          color: "#64748B",
          marginTop: 14,
          marginBottom: 0,
        }}
      >
        {t("auth.haveAccount", "Already have an account?")}{" "}
        <Link
          to="/login"
          style={{
            color: "#F97316",
            fontWeight: 700,
            textDecoration: "none",
          }}
        >
          {t("auth.signIn", "Sign In")}
        </Link>
      </p>
    </>
  );
}
