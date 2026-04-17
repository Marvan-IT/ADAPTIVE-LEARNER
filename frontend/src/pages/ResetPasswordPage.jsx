import { useState, useEffect } from "react";
import { useNavigate, useLocation, Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";
import { Lock, AlertCircle, ArrowLeft } from "lucide-react";
import { resetPassword } from "../api/auth";
import { StrengthBar, passwordStrength } from "../components/ui";

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

const inputError = {
  ...inputBase,
  border: "1.5px solid #DC2626",
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

// ── Component ──────────────────────────────────────────────────────────────────
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
      setError(
        t("auth.errorPasswordWeak", "Password is too weak. Add uppercase letters or numbers.")
      );
      return;
    }
    setError("");
    setLoading(true);
    try {
      await resetPassword(email, otp, newPassword);
      navigate("/login", {
        state: {
          successMsg: t(
            "auth.passwordResetSuccess",
            "Password reset successfully. Please log in."
          ),
        },
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

  // Compute confirm-field border: mismatch > focused > default
  const confirmHasMismatch = !!confirmPassword && newPassword !== confirmPassword;
  const isConfirmFocused = focusedField === "reset-confirm";
  const confirmInputStyle = confirmHasMismatch
    ? inputError
    : isConfirmFocused
    ? inputFocused
    : inputBase;

  return (
    <>
      <div style={card}>
        {/* Heading */}
        <h1
          style={{
            fontSize: 26,
            fontWeight: 800,
            color: "#1E293B",
            margin: "0 0 4px",
          }}
        >
          {t("auth.resetPasswordTitle", "Reset password")}
        </h1>
        <p style={{ fontSize: 14, color: "#94A3B8", margin: "0 0 24px" }}>
          {t("auth.resetPasswordSubtitle", "Choose a strong new password")}
        </p>

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
          {/* New password field */}
          <div style={{ marginBottom: 20 }}>
            <label htmlFor="reset-password" style={labelStyle}>
              {t("auth.newPasswordLabel", "New password")}
            </label>
            <div style={{ position: "relative" }}>
              <Lock
                size={16}
                style={focusedField === "reset-password" ? iconFocused : iconBase}
                aria-hidden="true"
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
                style={focusedField === "reset-password" ? inputFocused : inputBase}
              />
            </div>
            <StrengthBar password={newPassword} />
          </div>

          {/* Confirm password field */}
          <div style={{ marginBottom: 24 }}>
            <label htmlFor="reset-confirm" style={labelStyle}>
              {t("auth.confirmPasswordLabel", "Confirm password")}
            </label>
            <div style={{ position: "relative" }}>
              <Lock
                size={16}
                style={isConfirmFocused && !confirmHasMismatch ? iconFocused : iconBase}
                aria-hidden="true"
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
                style={confirmInputStyle}
              />
            </div>
            {confirmHasMismatch && (
              <p
                style={{
                  color: "#DC2626",
                  fontSize: 12,
                  margin: "4px 0 0",
                }}
              >
                {t("auth.passwordMismatchHint", "Passwords do not match")}
              </p>
            )}
          </div>

          {/* Submit button */}
          <button type="submit" disabled={!canSubmit} style={getButtonStyle(canSubmit)}>
            {loading
              ? t("auth.resetting", "Resetting...")
              : t("auth.resetPasswordButton", "Reset Password")}
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
