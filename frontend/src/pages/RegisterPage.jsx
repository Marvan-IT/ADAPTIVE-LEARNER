import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { motion, AnimatePresence } from "framer-motion";
import { User, Mail, Lock, AlertCircle } from "lucide-react";
import { registerUser } from "../api/auth";
import { Button, StrengthBar, passwordStrength } from "../components/ui";

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
    <div className="mb-3">
      <label
        htmlFor={id}
        className="block text-[12px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)] mb-1.5"
      >
        {label}
      </label>
      <div className="relative">
        {Icon && (
          <Icon
            size={15}
            className={`absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none transition-colors duration-150 ${
              isFocused
                ? "text-[var(--color-primary)]"
                : "text-[var(--color-border-strong)]"
            }`}
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
          className={`w-full h-[44px] bg-[var(--color-surface-2)] border-2 rounded-xl text-[var(--color-text)] text-[0.9rem] outline-none transition-[border-color,box-shadow] duration-150 ${
            Icon ? "pl-9 pr-3" : "px-3"
          } ${
            isFocused
              ? "border-[var(--color-primary)] ring-2 ring-[var(--color-primary)]/15"
              : "border-[var(--color-border)]"
          }`}
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
  const isDisabled = loading || strength.score < 2 || password !== confirmPassword || !displayName.trim() || !email.trim();

  return (
    <>
        {/* Card */}
        <div className="bg-[var(--color-surface)] rounded-2xl p-5 lg:p-6 shadow-sm">
          {/* Heading */}
          <h1 className="text-2xl font-bold text-[var(--color-text)] mb-1">
            {t("auth.joinAdventure", "Join the adventure!")}
          </h1>
          <p className="text-sm text-[var(--color-text-muted)] mb-4">
            {t("auth.registerSubtitle", "Start your learning journey today")}
          </p>

          {/* Error */}
          <AnimatePresence>
            {error && (
              <motion.div
                key="error"
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                className="flex items-center gap-2 rounded-[10px] px-4 py-3 mb-5 text-sm text-[var(--color-danger)]"
                style={{
                  background: "color-mix(in srgb, var(--color-danger) 8%, transparent)",
                  border: "1px solid color-mix(in srgb, var(--color-danger) 40%, transparent)",
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
                <p className="text-[var(--color-danger)] text-xs mt-1">
                  {t("auth.passwordMismatchHint", "Passwords do not match")}
                </p>
              )}
            </InputField>

            {/* Age */}
            <div className="mb-3">
              <label
                htmlFor="reg-age"
                className="block text-[12px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)] mb-1.5"
              >
                {t("auth.ageLabel", "Age")}{" "}
                <span className="font-normal normal-case text-xs">
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
                className={`w-full h-[44px] px-3 bg-[var(--color-surface-2)] border-2 rounded-xl text-[var(--color-text)] text-[0.9rem] outline-none transition-[border-color,box-shadow] duration-150 ${
                  focusedField === "reg-age"
                    ? "border-[var(--color-primary)] ring-2 ring-[var(--color-primary)]/15"
                    : "border-[var(--color-border)]"
                }`}
              />
            </div>

            {/* Language */}
            <div className="mb-4">
              <label
                htmlFor="reg-language"
                className="block text-[12px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)] mb-1.5"
              >
                {t("form.languageLabel", "Preferred Language")}
              </label>
              <select
                id="reg-language"
                value={preferredLanguage}
                onChange={(e) => setPreferredLanguage(e.target.value)}
                className="w-full h-[44px] px-3 bg-[var(--color-surface-2)] border-2 border-[var(--color-border)] rounded-xl text-[var(--color-text)] text-[0.9rem] outline-none cursor-pointer appearance-none"
              >
                {SUPPORTED_LANGUAGES.map((lang) => (
                  <option
                    key={lang.code}
                    value={lang.code}
                    className="bg-[var(--color-surface-2)]"
                  >
                    {lang.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Submit */}
            <Button
              type="submit"
              variant="primary"
              size="lg"
              loading={loading}
              disabled={isDisabled}
              className="w-full"
            >
              {t("auth.signUpButton", "Sign Up")}
            </Button>
          </form>
        </div>

        {/* Login link */}
        <p className="text-center text-[var(--color-text-muted)] text-sm mt-6 pb-8">
          {t("auth.haveAccount", "Already have an account?")}{" "}
          <Link
            to="/login"
            className="text-[var(--color-primary)] font-semibold no-underline hover:underline"
          >
            {t("auth.signIn", "Sign In")}
          </Link>
        </p>
    </>
  );
}
