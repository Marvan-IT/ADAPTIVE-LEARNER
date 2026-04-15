import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";
import { Mail, AlertCircle, ArrowLeft } from "lucide-react";
import { forgotPassword } from "../api/auth";
import { Button } from "../components/ui";

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

  return (
    <>
        {/* Card */}
        <div className="bg-[var(--color-surface)] rounded-2xl p-8 shadow-sm">
          {/* Large Mail icon */}
          <div className="flex justify-center mb-4">
            <div className="w-16 h-16 rounded-full bg-[var(--color-primary)]/10 flex items-center justify-center">
              <Mail size={32} className="text-[var(--color-primary)]" aria-hidden="true" />
            </div>
          </div>

          {/* Heading */}
          <h1 className="text-3xl font-bold text-[var(--color-text)] mb-2 text-center">
            {t("auth.forgotPasswordTitle", "Forgot password?")}
          </h1>
          <p className="text-[var(--color-text-muted)] mb-8 text-center text-sm">
            {t("auth.forgotPasswordSubtitle", "No worries, we'll send you a reset code.")}
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
            {/* Email */}
            <div className="mb-6">
              <label
                htmlFor="forgot-email"
                className="block text-[13px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)] mb-2"
              >
                {t("auth.emailLabel", "Email")}
              </label>
              <div className="relative">
                <Mail
                  size={16}
                  className={`absolute left-3.5 top-1/2 -translate-y-1/2 pointer-events-none transition-colors duration-150 ${
                    focusedField === "forgot-email"
                      ? "text-[var(--color-primary)]"
                      : "text-[var(--color-border-strong)]"
                  }`}
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
                  className={`w-full h-[52px] pl-10 pr-3.5 bg-[var(--color-surface-2)] border-2 rounded-2xl text-[var(--color-text)] text-[0.95rem] outline-none transition-[border-color,box-shadow] duration-150 ${
                    focusedField === "forgot-email"
                      ? "border-[var(--color-primary)] ring-2 ring-[var(--color-primary)]/15"
                      : "border-[var(--color-border)]"
                  }`}
                />
              </div>
            </div>

            {/* Submit */}
            <Button
              type="submit"
              variant="primary"
              size="lg"
              loading={loading}
              disabled={!email.trim()}
              className="w-full"
            >
              {t("auth.sendCodeButton", "Send Reset Code")}
            </Button>
          </form>
        </div>

        {/* Back to login */}
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
