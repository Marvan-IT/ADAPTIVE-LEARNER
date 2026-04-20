import { useState } from "react";
import { useNavigate, useLocation, Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";
import { Mail, Lock, AlertCircle, LogIn, CheckCircle2, Eye, EyeOff } from "lucide-react";
import { useAuth } from "../context/AuthContext";

// --- Style constants ---
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

const labelStyle = {
  display: "block",
  fontSize: 13,
  fontWeight: 600,
  color: "#64748B",
  marginBottom: 6,
};

const cardStyle = {
  background: "#FFFFFF",
  borderRadius: 20,
  padding: "32px 28px",
  boxShadow: "0 4px 24px rgba(0,0,0,0.07)",
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
  const [showPassword, setShowPassword] = useState(false);

  const from = location.state?.from?.pathname || null;
  const successMsg = location.state?.successMsg || null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!email.trim() || !password) return;
    setError("");
    setLoading(true);
    try {
      const user = await login(email.trim(), password);
      const dest = from || (user.role === "admin" ? "/admin" : "/dashboard");
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

  const canSubmit = email.trim() && password;

  const buttonStyle = {
    width: "100%",
    height: 48,
    background: canSubmit && !loading ? "linear-gradient(135deg, #F97316, #EA580C)" : "#FDBA74",
    color: "#FFFFFF",
    border: "none",
    borderRadius: 9999,
    fontSize: 15,
    fontWeight: 700,
    cursor: canSubmit && !loading ? "pointer" : "not-allowed",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    transition: "all 0.2s",
  };

  return (
    <>
      <div style={cardStyle}>
        <h1
          style={{
            fontSize: 26,
            fontWeight: 800,
            color: "#1E293B",
            marginBottom: 4,
            marginTop: 0,
          }}
        >
          {t("auth.welcomeBack", "Welcome back!")}
        </h1>
        <p
          style={{
            fontSize: 14,
            color: "#94A3B8",
            marginBottom: 28,
            marginTop: 0,
          }}
        >
          {t("auth.loginSubtitle", "Sign in to continue learning")}
        </p>

        {/* Success banner */}
        {successMsg && !error && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              borderRadius: 12,
              padding: "12px 16px",
              marginBottom: 20,
              fontSize: 14,
              color: "#16A34A",
              background: "rgba(22,163,74,0.07)",
              border: "1px solid rgba(22,163,74,0.22)",
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
            role="alert"
            style={{
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
            }}
          >
            <AlertCircle size={16} aria-hidden="true" />
            {error}
          </motion.div>
        )}

        <form onSubmit={handleSubmit} noValidate>
          {/* Email field */}
          <div style={{ marginBottom: 20 }}>
            <label htmlFor="login-email" style={labelStyle}>
              {t("auth.emailLabel", "Email")}
            </label>
            <div style={{ position: "relative" }}>
              <Mail
                size={18}
                style={focusedField === "email" ? iconFocused : iconBase}
                aria-hidden="true"
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
                style={focusedField === "email" ? inputFocused : inputBase}
              />
            </div>
          </div>

          {/* Password field */}
          <div style={{ marginBottom: 10 }}>
            <label htmlFor="login-password" style={labelStyle}>
              {t("auth.passwordLabel", "Password")}
            </label>
            <div style={{ position: "relative" }}>
              <Lock
                size={18}
                style={focusedField === "password" ? iconFocused : iconBase}
                aria-hidden="true"
              />
              <input
                id="login-password"
                type={showPassword ? "text" : "password"}
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onFocus={() => setFocusedField("password")}
                onBlur={() => setFocusedField(null)}
                placeholder="••••••••"
                required
                style={{
                  ...(focusedField === "password" ? inputFocused : inputBase),
                  paddingRight: 44,
                }}
              />
              <button
                type="button"
                onClick={() => setShowPassword((p) => !p)}
                aria-label={showPassword ? t("auth.hidePassword", "Hide password") : t("auth.showPassword", "Show password")}
                style={{
                  position: "absolute",
                  right: 14,
                  top: "50%",
                  transform: "translateY(-50%)",
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  padding: 0,
                  color: "#94A3B8",
                  display: "flex",
                  alignItems: "center",
                }}
              >
                {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>
            <div style={{ textAlign: "right", marginTop: 8 }}>
              <Link
                to="/forgot-password"
                style={{
                  fontSize: 13,
                  fontWeight: 600,
                  color: "#F97316",
                  textDecoration: "none",
                }}
              >
                {t("auth.forgotPassword", "Forgot password?")}
              </Link>
            </div>
          </div>

          {/* Submit */}
          <motion.button
            type="submit"
            disabled={loading || !canSubmit}
            whileHover={canSubmit && !loading ? { scale: 1.02 } : {}}
            whileTap={canSubmit && !loading ? { scale: 0.97 } : {}}
            style={buttonStyle}
          >
            {loading ? (
              <span
                style={{
                  width: 18,
                  height: 18,
                  border: "2.5px solid rgba(255,255,255,0.35)",
                  borderTopColor: "#FFFFFF",
                  borderRadius: "50%",
                  display: "inline-block",
                  animation: "spin 0.7s linear infinite",
                }}
                aria-hidden="true"
              />
            ) : (
              <LogIn size={18} aria-hidden="true" />
            )}
            {loading ? t("auth.loggingIn", "Signing in...") : t("auth.loginButton", "Log In")}
          </motion.button>
        </form>
      </div>

      {/* Register link */}
      <p
        style={{
          textAlign: "center",
          fontSize: 14,
          color: "#64748B",
          marginTop: 20,
          marginBottom: 0,
        }}
      >
        {t("auth.noAccount", "Don't have an account?")}{" "}
        <Link
          to="/register"
          style={{
            color: "#F97316",
            fontWeight: 700,
            textDecoration: "none",
          }}
        >
          {t("auth.createAccount", "Create Account")}
        </Link>
      </p>
    </>
  );
}
