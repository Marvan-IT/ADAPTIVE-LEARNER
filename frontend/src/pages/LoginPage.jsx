import { useState } from "react";
import { useNavigate, useLocation, Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";
import { Brain, Mail, Lock, AlertCircle, LogIn, CheckCircle2 } from "lucide-react";
import { useAuth } from "../context/AuthContext";

const PALETTE = {
  bg: "#0f0a1a",
  card: "#1a1025",
  accent: "#7c3aed",
  accentHover: "#6d28d9",
  accentGlow: "rgba(124,58,237,0.35)",
  text: "#e2e8f0",
  muted: "#94a3b8",
  inputBg: "#2d1f3d",
  inputBorder: "#4c3a6e",
  inputBorderFocus: "#7c3aed",
  error: "#ef4444",
  errorBg: "rgba(239,68,68,0.08)",
};

export default function LoginPage() {
  const { t } = useTranslation();
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [focusedField, setFocusedField] = useState(null);

  const from = location.state?.from?.pathname || null;
  const successMsg = location.state?.successMsg || null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!email.trim() || !password) return;
    setError("");
    setLoading(true);
    try {
      const user = await login(email.trim(), password);
      const dest = from || (user.role === "admin" ? "/admin" : "/map");
      navigate(dest, { replace: true });
    } catch (err) {
      const detail = err.response?.data?.detail;
      if (typeof detail === "string") {
        setError(detail);
      } else {
        setError(t("auth.loginError", "Invalid email or password."));
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        background: PALETTE.bg,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "1rem",
        fontFamily: "Inter, system-ui, sans-serif",
      }}
    >
      {/* Background radial glow */}
      <div
        aria-hidden="true"
        style={{
          position: "fixed",
          top: "30%",
          left: "50%",
          transform: "translate(-50%, -50%)",
          width: "600px",
          height: "600px",
          background:
            "radial-gradient(circle at 50% 50%, rgba(124,58,237,0.12), transparent 65%)",
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
          maxWidth: "420px",
        }}
      >
        {/* ADA branding */}
        <div style={{ textAlign: "center", marginBottom: "2rem" }}>
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              width: "56px",
              height: "56px",
              borderRadius: "16px",
              background: "rgba(124,58,237,0.15)",
              border: "1px solid rgba(124,58,237,0.3)",
              marginBottom: "1rem",
            }}
          >
            <Brain size={28} color="#a78bfa" aria-hidden="true" />
          </div>
          <h1
            style={{
              fontSize: "1.75rem",
              fontWeight: 800,
              color: PALETTE.text,
              letterSpacing: "-0.02em",
              margin: 0,
              marginBottom: "0.35rem",
            }}
          >
            {t("auth.welcomeBack", "Welcome back")}
          </h1>
          <p style={{ color: PALETTE.muted, fontSize: "0.9rem", margin: 0 }}>
            {t("auth.loginSubtitle", "Sign in to continue learning")}
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
          {/* Success banner (e.g. after password reset) */}
          {successMsg && !error && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              style={{
                background: "rgba(34,197,94,0.08)",
                border: "1px solid rgba(34,197,94,0.3)",
                borderRadius: "10px",
                padding: "0.75rem 1rem",
                marginBottom: "1.25rem",
                display: "flex",
                alignItems: "center",
                gap: "0.5rem",
                color: "#22c55e",
                fontSize: "0.875rem",
              }}
            >
              <CheckCircle2 size={16} aria-hidden="true" />
              {successMsg}
            </motion.div>
          )}

          {/* Error banner */}
          {error && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
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

          <form onSubmit={handleSubmit} noValidate>
            {/* Email field */}
            <div style={{ marginBottom: "1.1rem" }}>
              <label
                htmlFor="login-email"
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
                {t("auth.emailLabel", "Email")}
              </label>
              <div style={{ position: "relative" }}>
                <Mail
                  size={16}
                  color={
                    focusedField === "email" ? "#a78bfa" : PALETTE.inputBorder
                  }
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
                <input
                  id="login-email"
                  type="email"
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  onFocus={() => setFocusedField("email")}
                  onBlur={() => setFocusedField(null)}
                  placeholder={t("auth.emailPlaceholder", "you@example.com")}
                  required
                  style={{
                    width: "100%",
                    boxSizing: "border-box",
                    padding: "0.75rem 0.875rem 0.75rem 2.5rem",
                    background: PALETTE.inputBg,
                    border: `1px solid ${
                      focusedField === "email"
                        ? PALETTE.inputBorderFocus
                        : PALETTE.inputBorder
                    }`,
                    borderRadius: "10px",
                    color: PALETTE.text,
                    fontSize: "0.95rem",
                    outline: "none",
                    transition: "border-color 0.15s",
                  }}
                />
              </div>
            </div>

            {/* Password field */}
            <div style={{ marginBottom: "0.75rem" }}>
              <label
                htmlFor="login-password"
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
                {t("auth.passwordLabel", "Password")}
              </label>
              <div style={{ position: "relative" }}>
                <Lock
                  size={16}
                  color={
                    focusedField === "password"
                      ? "#a78bfa"
                      : PALETTE.inputBorder
                  }
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
                <input
                  id="login-password"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  onFocus={() => setFocusedField("password")}
                  onBlur={() => setFocusedField(null)}
                  placeholder="••••••••"
                  required
                  style={{
                    width: "100%",
                    boxSizing: "border-box",
                    padding: "0.75rem 0.875rem 0.75rem 2.5rem",
                    background: PALETTE.inputBg,
                    border: `1px solid ${
                      focusedField === "password"
                        ? PALETTE.inputBorderFocus
                        : PALETTE.inputBorder
                    }`,
                    borderRadius: "10px",
                    color: PALETTE.text,
                    fontSize: "0.95rem",
                    outline: "none",
                    transition: "border-color 0.15s",
                  }}
                />
              </div>
            </div>

            {/* Forgot password */}
            <div style={{ textAlign: "right", marginBottom: "1.5rem" }}>
              <Link
                to="/forgot-password"
                style={{
                  color: "#a78bfa",
                  fontSize: "0.85rem",
                  textDecoration: "none",
                  fontWeight: 500,
                }}
              >
                {t("auth.forgotPassword", "Forgot password?")}
              </Link>
            </div>

            {/* Submit */}
            <button
              type="submit"
              disabled={loading || !email.trim() || !password}
              style={{
                width: "100%",
                padding: "0.875rem",
                background:
                  loading || !email.trim() || !password
                    ? "rgba(124,58,237,0.4)"
                    : PALETTE.accent,
                color: "#fff",
                border: "none",
                borderRadius: "10px",
                fontSize: "0.95rem",
                fontWeight: 700,
                cursor:
                  loading || !email.trim() || !password
                    ? "not-allowed"
                    : "pointer",
                transition: "background 0.15s, transform 0.1s",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: "0.5rem",
                letterSpacing: "0.01em",
              }}
              onMouseEnter={(e) => {
                if (!loading && email.trim() && password) {
                  e.currentTarget.style.background = PALETTE.accentHover;
                }
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background =
                  loading || !email.trim() || !password
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
                  {t("auth.loggingIn", "Signing in...")}
                </>
              ) : (
                <>
                  <LogIn size={16} aria-hidden="true" />
                  {t("auth.loginButton", "Log In")}
                </>
              )}
            </button>
          </form>
        </div>

        {/* Register link */}
        <p
          style={{
            textAlign: "center",
            color: PALETTE.muted,
            fontSize: "0.9rem",
            marginTop: "1.5rem",
          }}
        >
          {t("auth.noAccount", "Don't have an account?")}{" "}
          <Link
            to="/register"
            style={{
              color: "#a78bfa",
              fontWeight: 600,
              textDecoration: "none",
            }}
          >
            {t("auth.createAccount", "Create Account")}
          </Link>
        </p>
      </motion.div>
    </div>
  );
}
