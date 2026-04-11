import { useState, useEffect } from "react";
import { useNavigate, useLocation, Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";
import { Brain, Lock, AlertCircle, ArrowLeft } from "lucide-react";
import { resetPassword } from "../api/auth";

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
};

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
      <div style={{ display: "flex", gap: "4px", marginBottom: "4px" }}>
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

export default function ResetPasswordPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();

  const email = location.state?.email || "";
  const otp = location.state?.otp || "";

  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [focusedField, setFocusedField] = useState(null);

  // Redirect to forgot-password if no email in state
  useEffect(() => {
    if (!email || !otp) {
      navigate("/forgot-password", { replace: true });
    }
  }, [email, otp, navigate]);

  const strength = passwordStrength(newPassword);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!newPassword || !confirmPassword) return;
    if (newPassword.length < 8) {
      setError(t("auth.errorPasswordShort", "Password must be at least 8 characters."));
      return;
    }
    if (newPassword !== confirmPassword) {
      setError(t("auth.errorPasswordMismatch", "Passwords do not match."));
      return;
    }
    if (strength.score < 2) {
      setError(t("auth.errorPasswordWeak", "Password is too weak. Add uppercase letters or numbers."));
      return;
    }
    setError("");
    setLoading(true);
    try {
      await resetPassword(email, otp, newPassword);
      navigate("/login", {
        state: { successMsg: t("auth.passwordResetSuccess", "Password reset successfully. Please log in.") },
      });
    } catch (err) {
      const detail = err.response?.data?.detail;
      setError(
        typeof detail === "string"
          ? detail
          : t("auth.resetError", "Could not reset password. The code may have expired.")
      );
    } finally {
      setLoading(false);
    }
  };

  const canSubmit =
    newPassword.length >= 8 &&
    newPassword === confirmPassword &&
    strength.score >= 2 &&
    !loading;

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
      {/* Background glow */}
      <div
        aria-hidden="true"
        style={{
          position: "fixed",
          top: "30%",
          left: "50%",
          transform: "translate(-50%, -50%)",
          width: "500px",
          height: "500px",
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
          maxWidth: "400px",
        }}
      >
        {/* Branding */}
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
              fontSize: "1.65rem",
              fontWeight: 800,
              color: PALETTE.text,
              letterSpacing: "-0.02em",
              margin: 0,
              marginBottom: "0.4rem",
            }}
          >
            {t("auth.resetPasswordTitle", "Set new password")}
          </h1>
          <p
            style={{
              color: PALETTE.muted,
              fontSize: "0.875rem",
              margin: 0,
              lineHeight: 1.6,
            }}
          >
            {t("auth.resetPasswordSubtitle", "Choose a strong password for your account.")}
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
            {/* New password */}
            <div style={{ marginBottom: "1.1rem" }}>
              <label
                htmlFor="reset-password"
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
                {t("auth.newPasswordLabel", "New Password")}
              </label>
              <div style={{ position: "relative" }}>
                <Lock
                  size={16}
                  color={
                    focusedField === "reset-password"
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
                  id="reset-password"
                  type="password"
                  autoComplete="new-password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  onFocus={() => setFocusedField("reset-password")}
                  onBlur={() => setFocusedField(null)}
                  placeholder="••••••••"
                  required
                  autoFocus
                  style={{
                    width: "100%",
                    boxSizing: "border-box",
                    padding: "0.75rem 0.875rem 0.75rem 2.5rem",
                    background: PALETTE.inputBg,
                    border: `1px solid ${
                      focusedField === "reset-password"
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
              <StrengthBar password={newPassword} />
            </div>

            {/* Confirm password */}
            <div style={{ marginBottom: "1.5rem" }}>
              <label
                htmlFor="reset-confirm"
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
                {t("auth.confirmPasswordLabel", "Confirm Password")}
              </label>
              <div style={{ position: "relative" }}>
                <Lock
                  size={16}
                  color={
                    focusedField === "reset-confirm"
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
                  id="reset-confirm"
                  type="password"
                  autoComplete="new-password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  onFocus={() => setFocusedField("reset-confirm")}
                  onBlur={() => setFocusedField(null)}
                  placeholder="••••••••"
                  required
                  style={{
                    width: "100%",
                    boxSizing: "border-box",
                    padding: "0.75rem 0.875rem 0.75rem 2.5rem",
                    background: PALETTE.inputBg,
                    border: `1px solid ${
                      confirmPassword && newPassword !== confirmPassword
                        ? PALETTE.error
                        : focusedField === "reset-confirm"
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
              {confirmPassword && newPassword !== confirmPassword && (
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
            </div>

            {/* Submit */}
            <button
              type="submit"
              disabled={!canSubmit}
              style={{
                width: "100%",
                padding: "0.875rem",
                background: !canSubmit ? "rgba(124,58,237,0.4)" : PALETTE.accent,
                color: "#fff",
                border: "none",
                borderRadius: "10px",
                fontSize: "0.95rem",
                fontWeight: 700,
                cursor: !canSubmit ? "not-allowed" : "pointer",
                transition: "background 0.15s",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: "0.5rem",
                letterSpacing: "0.01em",
              }}
              onMouseEnter={(e) => {
                if (canSubmit) e.currentTarget.style.background = PALETTE.accentHover;
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = !canSubmit
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
                  {t("auth.resettingPassword", "Resetting...")}
                </>
              ) : (
                t("auth.resetPasswordButton", "Reset Password")
              )}
            </button>
          </form>
        </div>

        {/* Back link */}
        <p
          style={{
            textAlign: "center",
            color: PALETTE.muted,
            fontSize: "0.875rem",
            marginTop: "1.5rem",
          }}
        >
          <Link
            to="/login"
            style={{
              color: "#a78bfa",
              textDecoration: "none",
              fontWeight: 500,
              display: "inline-flex",
              alignItems: "center",
              gap: "4px",
            }}
          >
            <ArrowLeft size={14} aria-hidden="true" />
            {t("auth.backToLogin", "Back to Login")}
          </Link>
        </p>
      </motion.div>
    </div>
  );
}
