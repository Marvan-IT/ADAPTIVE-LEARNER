import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";
import { Mail, AlertCircle, ArrowLeft } from "lucide-react";
import { forgotPassword } from "../api/auth";

// ── Shared style tokens ────────────────────────────────────────────────────────
const card = {
  background: "#fff",
  borderRadius: 20,
  padding: "32px 28px",
  boxShadow: "0 4px 24px rgba(0,0,0,0.07)",
};

const inputBase = {
  width: "100%",
  height: 48,
  paddingLeft: 44,
  paddingRight: 16,
  background: "#F8FAFC",
  border: "1.5px solid #E2E8F0",
  borderRadius: 12,
  fontSize: 15,
  color: "#1E293B",
  outline: "none",
  transition: "border-color 0.2s, box-shadow 0.2s",
  boxSizing: "border-box",
};

const inputFocused = {
  ...inputBase,
  border: "1.5px solid #F97316",
  boxShadow: "0 0 0 3px rgba(249,115,22,0.12)",
};

const labelStyle = {
  display: "block",
  fontSize: 13,
  fontWeight: 600,
  color: "#64748B",
  marginBottom: 6,
};

const iconBase = {
  position: "absolute",
  left: 14,
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

const errorBannerStyle = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  borderRadius: 12,
  padding: "12px 16px",
  marginBottom: 20,
  fontSize: 14,
  color: "#DC2626",
  background: "rgba(239,68,68,0.06)",
  border: "1px solid rgba(239,68,68,0.2)",
};

const bottomLink = {
  textAlign: "center",
  fontSize: 14,
  color: "#64748B",
  marginTop: 20,
};

const orangeLink = {
  color: "#F97316",
  fontWeight: 600,
  textDecoration: "none",
  display: "inline-flex",
  alignItems: "center",
  gap: 4,
};

const getButtonStyle = (enabled) => ({
  width: "100%",
  height: 48,
  background: enabled ? "linear-gradient(135deg, #F97316, #EA580C)" : "#FDBA74",
  color: "#fff",
  border: "none",
  borderRadius: 9999,
  fontSize: 15,
  fontWeight: 700,
  cursor: enabled ? "pointer" : "not-allowed",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  gap: 8,
  transition: "all 0.2s",
});

// ── Component ──────────────────────────────────────────────────────────────────
export default function ForgotPasswordPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [focusedField, setFocusedField] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!email.trim()) return;
    setError("");
    setLoading(true);
    try {
      await forgotPassword(email.trim());
      navigate("/verify-otp", {
        state: { email: email.trim(), purpose: "password_reset" },
      });
    } catch (err) {
      const detail = err.response?.data?.detail;
      setError(
        typeof detail === "string"
          ? detail
          : t("auth.forgotError", "Could not send reset code. Please check the email address.")
      );
    } finally {
      setLoading(false);
    }
  };

  const isEmailFocused = focusedField === "forgot-email";
  const canSubmit = !!email.trim() && !loading;

  return (
    <>
      <div style={card}>
        {/* Icon + heading */}
        <div style={{ textAlign: "center", marginBottom: 20 }}>
          <div
            style={{
              width: 56,
              height: 56,
              borderRadius: "50%",
              background: "rgba(249,115,22,0.1)",
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              marginBottom: 12,
            }}
          >
            <Mail size={26} style={{ color: "#F97316" }} aria-hidden="true" />
          </div>
          <h1
            style={{
              fontSize: 26,
              fontWeight: 800,
              color: "#1E293B",
              margin: "0 0 4px",
            }}
          >
            {t("auth.forgotPasswordTitle", "Forgot password?")}
          </h1>
          <p style={{ fontSize: 14, color: "#94A3B8", margin: 0 }}>
            {t("auth.forgotPasswordSubtitle", "We'll send a code to your email")}
          </p>
        </div>

        {/* Error banner */}
        {error && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            style={errorBannerStyle}
            role="alert"
          >
            <AlertCircle size={16} aria-hidden="true" />
            {error}
          </motion.div>
        )}

        <form onSubmit={handleSubmit} noValidate>
          {/* Email field */}
          <div style={{ marginBottom: 24 }}>
            <label htmlFor="forgot-email" style={labelStyle}>
              {t("auth.emailLabel", "Email")}
            </label>
            <div style={{ position: "relative" }}>
              <Mail
                size={16}
                style={isEmailFocused ? iconFocused : iconBase}
                aria-hidden="true"
              />
              <input
                id="forgot-email"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                onFocus={() => setFocusedField("forgot-email")}
                onBlur={() => setFocusedField(null)}
                placeholder={t("auth.emailPlaceholder", "you@example.com")}
                required
                autoFocus
                style={isEmailFocused ? inputFocused : inputBase}
              />
            </div>
          </div>

          {/* Submit button */}
          <button type="submit" disabled={!canSubmit} style={getButtonStyle(canSubmit)}>
            {loading
              ? t("auth.sending", "Sending...")
              : t("auth.sendCodeButton", "Send Reset Code")}
          </button>
        </form>
      </div>

      {/* Back to login */}
      <p style={bottomLink}>
        <Link to="/login" style={orangeLink}>
          <ArrowLeft size={14} aria-hidden="true" />
          {t("auth.backToLogin", "Back to Login")}
        </Link>
      </p>
    </>
  );
}
