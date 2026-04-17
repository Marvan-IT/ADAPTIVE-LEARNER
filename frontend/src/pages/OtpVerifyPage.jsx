import { useState, useRef, useEffect, useCallback } from "react";
import { useNavigate, useLocation, Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";
import { AlertCircle, CheckCircle2, Mail } from "lucide-react";
import { verifyOtp, resendOtp } from "../api/auth";
import { useAuth } from "../context/AuthContext";
import { Button } from "../components/ui";

const RESEND_COOLDOWN = 60;

export default function OtpVerifyPage() {
  const { t } = useTranslation();
  const { setUser, setTokens, doRefresh } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const email = location.state?.email || "";
  const purpose = location.state?.purpose || "email_verify";

  const [digits, setDigits] = useState(["", "", "", "", "", ""]);
  const [error, setError] = useState("");
  const [successMsg, setSuccessMsg] = useState("");
  const [loading, setLoading] = useState(false);
  const [resendLoading, setResendLoading] = useState(false);
  const [cooldown, setCooldown] = useState(0);

  const inputRefs = useRef([]);

  // Redirect to login if no email in state
  useEffect(() => {
    if (!email) {
      navigate("/login", { replace: true });
    }
  }, [email, navigate]);

  // Cooldown countdown
  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => clearTimeout(timer);
  }, [cooldown]);

  const submitOtp = useCallback(
    async (code) => {
      if (loading) return;
      setError("");
      setLoading(true);
      try {
        if (purpose === "password_reset") {
          // Skip verify-otp API — the OTP will be verified by /reset-password
          // to avoid double consumption (verify-otp marks it used, then
          // reset-password can't find an unused OTP).
          navigate("/reset-password", { state: { email, otp: code } });
          return;
        }
        const { data } = await verifyOtp(email, code, purpose);
        // Auto-login: backend returns tokens after email verification
        if (data.access_token) {
          if (data.refresh_token) {
            localStorage.setItem("ada_refresh_token", data.refresh_token);
          }
          // Trigger doRefresh to properly initialize the auth state
          const newToken = await doRefresh();
          if (!newToken) {
            // Fallback: set tokens manually
            setTokens(data.access_token, data.refresh_token);
            setUser(data.user);
          }
        }
        navigate("/map", { replace: true });
      } catch (err) {
        const detail = err.response?.data?.detail;
        setError(
          typeof detail === "string"
            ? detail
            : t("auth.otpInvalid", "Invalid or expired code. Please try again.")
        );
        // Clear inputs for retry
        setDigits(["", "", "", "", "", ""]);
        inputRefs.current[0]?.focus();
      } finally {
        setLoading(false);
      }
    },
    [email, purpose, loading, navigate, setUser, setTokens, doRefresh, t]
  );

  const handleDigitChange = (index, value) => {
    // Allow only single digit
    const digit = value.replace(/\D/g, "").slice(-1);
    const newDigits = [...digits];
    newDigits[index] = digit;
    setDigits(newDigits);

    if (digit && index < 5) {
      inputRefs.current[index + 1]?.focus();
    }

    // Auto-submit when all 6 digits entered
    const allFilled = newDigits.every((d) => d !== "");
    if (allFilled) {
      submitOtp(newDigits.join(""));
    }
  };

  const handleKeyDown = (index, e) => {
    if (e.key === "Backspace") {
      if (digits[index]) {
        const newDigits = [...digits];
        newDigits[index] = "";
        setDigits(newDigits);
      } else if (index > 0) {
        inputRefs.current[index - 1]?.focus();
        const newDigits = [...digits];
        newDigits[index - 1] = "";
        setDigits(newDigits);
      }
    } else if (e.key === "ArrowLeft" && index > 0) {
      inputRefs.current[index - 1]?.focus();
    } else if (e.key === "ArrowRight" && index < 5) {
      inputRefs.current[index + 1]?.focus();
    }
  };

  const handlePaste = (e) => {
    e.preventDefault();
    const pasted = e.clipboardData.getData("text").replace(/\D/g, "").slice(0, 6);
    if (!pasted) return;
    const newDigits = [...digits];
    for (let i = 0; i < 6; i++) {
      newDigits[i] = pasted[i] || "";
    }
    setDigits(newDigits);
    const lastFilled = Math.min(pasted.length, 5);
    inputRefs.current[lastFilled]?.focus();
    if (pasted.length === 6) {
      submitOtp(pasted);
    }
  };

  const handleResend = async () => {
    if (resendLoading || cooldown > 0) return;
    setResendLoading(true);
    setError("");
    setSuccessMsg("");
    try {
      await resendOtp(email, purpose);
      setSuccessMsg(t("auth.otpResent", "A new code has been sent to your email."));
      setCooldown(RESEND_COOLDOWN);
    } catch (err) {
      const detail = err.response?.data?.detail;
      setError(
        typeof detail === "string"
          ? detail
          : t("auth.resendError", "Could not resend code. Try again shortly.")
      );
    } finally {
      setResendLoading(false);
    }
  };

  const allFilled = digits.every((d) => d !== "");

  return (
    <>
        {/* Card */}
        <div className="bg-[var(--color-surface)] rounded-2xl p-8 shadow-sm">
          {/* Animated mail icon */}
          <div className="flex justify-center mb-6">
            <motion.div
              animate={{ y: [0, -6, 0] }}
              transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
              className="w-16 h-16 rounded-full bg-[var(--color-primary)]/10 flex items-center justify-center"
            >
              <Mail size={32} className="text-[var(--color-primary)]" aria-hidden="true" />
            </motion.div>
          </div>

          {/* Heading */}
          <h1 className="text-3xl font-bold text-[var(--color-text)] mb-2 text-center">
            {t("auth.checkEmail", "Check your email!")}
          </h1>
          <p className="text-[var(--color-text-muted)] mb-8 text-center text-sm">
            {t("auth.otpSentTo", "We sent a 6-digit code to")} <span className="font-semibold text-[var(--color-text)]">{email}</span>
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

          {/* Success */}
          {successMsg && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              className="flex items-center gap-2 rounded-[10px] px-4 py-3 mb-5 text-sm text-[var(--color-success)]"
              style={{
                background: "color-mix(in srgb, var(--color-success) 8%, transparent)",
                border: "1px solid color-mix(in srgb, var(--color-success) 40%, transparent)",
              }}
            >
              <CheckCircle2 size={16} aria-hidden="true" />
              {successMsg}
            </motion.div>
          )}

          {/* OTP digit inputs */}
          <fieldset
            className="border-none p-0 m-0"
            aria-label={t("auth.otpFieldset", "6-digit verification code")}
          >
            <div
              className="flex gap-2.5 justify-center mb-8"
              onPaste={handlePaste}
            >
              {digits.map((digit, index) => (
                <input
                  key={index}
                  ref={(el) => { inputRefs.current[index] = el; }}
                  type="text"
                  inputMode="numeric"
                  maxLength={1}
                  value={digit}
                  onChange={(e) => handleDigitChange(index, e.target.value)}
                  onKeyDown={(e) => handleKeyDown(index, e)}
                  aria-label={t("auth.otpDigitN", { n: index + 1 }, `Digit ${index + 1}`)}
                  disabled={loading}
                  autoFocus={index === 0}
                  className={`w-[56px] h-[56px] text-center text-2xl font-bold bg-[var(--color-surface-2)] border-2 rounded-xl text-[var(--color-text)] outline-none transition-[border-color,transform,box-shadow] duration-150 caret-[var(--color-primary)] ${
                    digit ? "border-[var(--color-primary)] scale-[1.04]" : "border-[var(--color-border)]"
                  } ${loading ? "cursor-not-allowed" : "cursor-text"} focus:border-[var(--color-primary)] focus:ring-2 focus:ring-[var(--color-primary)]/15`}
                />
              ))}
            </div>
          </fieldset>

          {/* Submit button (manual) */}
          <Button
            type="button"
            variant="primary"
            size="lg"
            loading={loading}
            disabled={!allFilled || loading}
            onClick={() => allFilled && submitOtp(digits.join(""))}
            className="w-full mb-5"
          >
            {t("auth.verifyButton", "Verify Code")}
          </Button>

          {/* Resend */}
          <p className="text-center text-[var(--color-text-muted)] text-sm mt-2">
            {t("auth.didntGetCode", "Didn't get a code?")}{" "}
            {cooldown > 0 ? (
              <span className="text-[var(--color-text-muted)]">
                {t("auth.resendIn", "Resend in {{s}}s", { s: cooldown })}
              </span>
            ) : (
              <button
                type="button"
                onClick={handleResend}
                disabled={resendLoading}
                className={`bg-transparent border-none p-0 text-[var(--color-primary)] font-semibold text-sm underline underline-offset-2 ${
                  resendLoading ? "cursor-wait" : "cursor-pointer"
                }`}
              >
                {resendLoading
                  ? t("auth.resending", "Resending...")
                  : t("auth.resendCode", "Resend code")}
              </button>
            )}
          </p>
        </div>

        {/* Back link */}
        <p className="text-center text-[var(--color-text-muted)] text-sm mt-6">
          <Link
            to="/login"
            className="text-[var(--color-primary)] no-underline font-medium hover:underline"
          >
            {t("auth.backToLogin", "Back to Login")}
          </Link>
        </p>
    </>
  );
}
