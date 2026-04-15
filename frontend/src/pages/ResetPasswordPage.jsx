import { useState, useEffect } from "react";
import { useNavigate, useLocation, Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";
import { Lock, AlertCircle, ArrowLeft } from "lucide-react";
import { resetPassword } from "../api/auth";
import { Button, StrengthBar, passwordStrength } from "../components/ui";

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
    <>
        {/* Card */}
        <div className="bg-[var(--color-surface)] rounded-2xl p-8 shadow-sm">
          {/* Heading */}
          <h1 className="text-3xl font-bold text-[var(--color-text)] mb-2 text-center">
            {t("auth.resetPasswordTitle", "Set new password")}
          </h1>
          <p className="text-[var(--color-text-muted)] mb-8 text-center text-sm">
            {t("auth.resetPasswordSubtitle", "Choose a strong password for your account.")}
          </p>

          {/* Error */}
          {error && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
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

          <form onSubmit={handleSubmit} noValidate>
            {/* New password */}
            <div className="mb-4">
              <label
                htmlFor="reset-password"
                className="block text-[13px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)] mb-2"
              >
                {t("auth.newPasswordLabel", "New Password")}
              </label>
              <div className="relative">
                <Lock
                  size={16}
                  className={`absolute left-3.5 top-1/2 -translate-y-1/2 pointer-events-none transition-colors duration-150 ${
                    focusedField === "reset-password"
                      ? "text-[var(--color-primary)]"
                      : "text-[var(--color-border-strong)]"
                  }`}
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
                  className={`w-full h-[52px] pl-10 pr-3.5 bg-[var(--color-surface-2)] border-2 rounded-2xl text-[var(--color-text)] text-[0.95rem] outline-none transition-[border-color,box-shadow] duration-150 ${
                    focusedField === "reset-password"
                      ? "border-[var(--color-primary)] ring-2 ring-[var(--color-primary)]/15"
                      : "border-[var(--color-border)]"
                  }`}
                />
              </div>
              <StrengthBar password={newPassword} />
            </div>

            {/* Confirm password */}
            <div className="mb-6">
              <label
                htmlFor="reset-confirm"
                className="block text-[13px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)] mb-2"
              >
                {t("auth.confirmPasswordLabel", "Confirm Password")}
              </label>
              <div className="relative">
                <Lock
                  size={16}
                  className={`absolute left-3.5 top-1/2 -translate-y-1/2 pointer-events-none transition-colors duration-150 ${
                    focusedField === "reset-confirm"
                      ? "text-[var(--color-primary)]"
                      : "text-[var(--color-border-strong)]"
                  }`}
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
                  className={`w-full h-[52px] pl-10 pr-3.5 bg-[var(--color-surface-2)] border-2 rounded-2xl text-[var(--color-text)] text-[0.95rem] outline-none transition-[border-color,box-shadow] duration-150 ${
                    confirmPassword && newPassword !== confirmPassword
                      ? "border-[var(--color-danger)]"
                      : focusedField === "reset-confirm"
                      ? "border-[var(--color-primary)] ring-2 ring-[var(--color-primary)]/15"
                      : "border-[var(--color-border)]"
                  }`}
                />
              </div>
              {confirmPassword && newPassword !== confirmPassword && (
                <p className="text-[var(--color-danger)] text-xs mt-1">
                  {t("auth.passwordMismatchHint", "Passwords do not match")}
                </p>
              )}
            </div>

            {/* Submit */}
            <Button
              type="submit"
              variant="primary"
              size="lg"
              loading={loading}
              disabled={!canSubmit}
              className="w-full"
            >
              {t("auth.resetPasswordButton", "Reset Password")}
            </Button>
          </form>
        </div>

        {/* Back link */}
        <p className="text-center text-sm mt-6">
          <Link
            to="/login"
            className="inline-flex items-center gap-1 text-[var(--color-primary)] no-underline font-medium hover:underline"
          >
            <ArrowLeft size={14} aria-hidden="true" />
            {t("auth.backToLogin", "Back to Login")}
          </Link>
        </p>
    </>
  );
}
