import { useState } from "react";
import { useNavigate, useLocation, Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";
import { Mail, Lock, AlertCircle, LogIn, CheckCircle2 } from "lucide-react";
import { useAuth } from "../context/AuthContext";

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

  const inputStyle = (focused) => ({
    width: "100%",
    height: "52px",
    paddingLeft: "44px",
    paddingRight: "16px",
    backgroundColor: "#FFFFFF",
    border: focused ? "2px solid #F97316" : "2px solid #CBD5E1",
    borderRadius: "12px",
    color: "#0F172A",
    fontSize: "0.95rem",
    outline: "none",
    transition: "border-color 0.15s, box-shadow 0.15s",
    boxShadow: focused ? "0 0 0 3px rgba(249,115,22,0.15)" : "none",
  });

  const iconStyle = (focused) => ({
    position: "absolute",
    left: "16px",
    top: "50%",
    transform: "translateY(-50%)",
    pointerEvents: "none",
    color: focused ? "#F97316" : "#94A3B8",
    transition: "color 0.15s",
  });

  return (
    <>
      {/* Card */}
      <div style={{
        backgroundColor: "#FFFFFF",
        borderRadius: "16px",
        padding: "40px 36px",
        boxShadow: "0 4px 24px rgba(0,0,0,0.08)",
      }}>
        {/* Heading */}
        <h1 style={{ fontFamily: "'Outfit', sans-serif", fontWeight: 700, fontSize: "32px", color: "#0F172A", marginBottom: "6px" }}>
          {t("auth.welcomeBack", "Welcome back!")}
        </h1>
        <p style={{ color: "#64748B", fontSize: "15px", marginBottom: "32px" }}>
          {t("auth.loginSubtitle", "Sign in to continue learning")}
        </p>

        {/* Success banner */}
        {successMsg && !error && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            style={{
              display: "flex", alignItems: "center", gap: "8px",
              borderRadius: "12px", padding: "12px 16px", marginBottom: "20px",
              fontSize: "14px", color: "#16A34A",
              background: "rgba(34,197,94,0.08)", border: "1px solid rgba(34,197,94,0.3)",
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
              display: "flex", alignItems: "center", gap: "8px",
              borderRadius: "12px", padding: "12px 16px", marginBottom: "20px",
              fontSize: "14px", color: "#DC2626",
              background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.3)",
            }}
            role="alert"
          >
            <AlertCircle size={16} aria-hidden="true" />
            {error}
          </motion.div>
        )}

        <form onSubmit={handleSubmit} noValidate>
          {/* Email field */}
          <div style={{ marginBottom: "24px" }}>
            <label
              htmlFor="login-email"
              style={{ display: "block", fontSize: "13px", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", color: "#64748B", marginBottom: "8px" }}
            >
              {t("auth.emailLabel", "Email")}
            </label>
            <div style={{ position: "relative" }}>
              <Mail size={18} style={iconStyle(focusedField === "email")} aria-hidden="true" />
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
                style={inputStyle(focusedField === "email")}
              />
            </div>
          </div>

          {/* Password field */}
          <div style={{ marginBottom: "24px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
              <label
                htmlFor="login-password"
                style={{ fontSize: "13px", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", color: "#64748B" }}
              >
                {t("auth.passwordLabel", "Password")}
              </label>
              <Link
                to="/forgot-password"
                style={{ color: "#F97316", fontSize: "14px", fontWeight: 500, textDecoration: "none" }}
              >
                {t("auth.forgotPassword", "Forgot password?")}
              </Link>
            </div>
            <div style={{ position: "relative" }}>
              <Lock size={18} style={iconStyle(focusedField === "password")} aria-hidden="true" />
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
                style={inputStyle(focusedField === "password")}
              />
            </div>
          </div>

          {/* Submit */}
          <motion.button
            type="submit"
            disabled={loading || !canSubmit}
            whileHover={canSubmit && !loading ? { scale: 1.01 } : {}}
            whileTap={canSubmit && !loading ? { scale: 0.98 } : {}}
            style={{
              width: "100%",
              height: "52px",
              backgroundColor: canSubmit && !loading ? "#EA580C" : "#FDBA74",
              color: "#FFFFFF",
              border: "none",
              borderRadius: "9999px",
              fontSize: "16px",
              fontWeight: 700,
              fontFamily: "'Outfit', sans-serif",
              cursor: canSubmit && !loading ? "pointer" : "not-allowed",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: "8px",
              transition: "background-color 0.15s",
            }}
          >
            {loading ? (
              <div style={{ width: "18px", height: "18px", border: "2px solid rgba(255,255,255,0.4)", borderTopColor: "#fff", borderRadius: "50%", animation: "spin 0.7s linear infinite" }} aria-hidden="true" />
            ) : (
              <LogIn size={18} aria-hidden="true" />
            )}
            {loading ? t("auth.loggingIn", "Signing in...") : t("auth.loginButton", "Log In")}
          </motion.button>

        </form>
      </div>

      {/* Register link */}
      <p style={{ textAlign: "center", color: "#64748B", fontSize: "14px", marginTop: "24px" }}>
        {t("auth.noAccount", "Don't have an account?")}{" "}
        <Link to="/register" style={{ color: "#F97316", fontWeight: 600, textDecoration: "none" }}>
          {t("auth.createAccount", "Create Account")}
        </Link>
      </p>
    </>
  );
}
