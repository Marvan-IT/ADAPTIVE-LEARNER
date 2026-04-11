import { useState, useRef, useEffect, useCallback } from "react";
import { useNavigate, useLocation, Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";
import { Brain, Mail, AlertCircle, CheckCircle2 } from "lucide-react";
import { verifyOtp, resendOtp } from "../api/auth";
import { useAuth } from "../context/AuthContext";

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
  successBg: "rgba(34,197,94,0.08)",
};

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
        const { data } = await verifyOtp(email, code);
        if (purpose === "email_verify") {
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
        } else {
          // password_reset: navigate to reset page with email
          navigate("/reset-password", { state: { email, otp: code } });
        }
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

  const titleKey =
    purpose === "password_reset" ? "auth.verifyResetCode" : "auth.verifyEmail";
  const titleDefault =
    purpose === "password_reset" ? "Enter reset code" : "Verify your email";

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
              marginBottom: "0.5rem",
            }}
          >
            {t(titleKey, titleDefault)}
          </h1>
          <p
            style={{
              color: PALETTE.muted,
              fontSize: "0.875rem",
              margin: 0,
              lineHeight: 1.6,
            }}
          >
            {t("auth.otpSentTo", "We've sent a 6-digit code to")}
          </p>
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "6px",
              marginTop: "6px",
              background: "rgba(124,58,237,0.1)",
              border: "1px solid rgba(124,58,237,0.2)",
              borderRadius: "8px",
              padding: "4px 12px",
            }}
          >
            <Mail size={13} color="#a78bfa" aria-hidden="true" />
            <span
              style={{
                color: "#c4b5fd",
                fontSize: "0.875rem",
                fontWeight: 500,
              }}
            >
              {email}
            </span>
          </div>
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

          {/* Success */}
          {successMsg && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              style={{
                background: PALETTE.successBg,
                border: `1px solid ${PALETTE.success}40`,
                borderRadius: "10px",
                padding: "0.75rem 1rem",
                marginBottom: "1.25rem",
                display: "flex",
                alignItems: "center",
                gap: "0.5rem",
                color: PALETTE.success,
                fontSize: "0.875rem",
              }}
            >
              <CheckCircle2 size={16} aria-hidden="true" />
              {successMsg}
            </motion.div>
          )}

          {/* OTP digit inputs */}
          <fieldset
            style={{ border: "none", padding: 0, margin: 0 }}
            aria-label={t("auth.otpFieldset", "6-digit verification code")}
          >
            <div
              style={{
                display: "flex",
                gap: "10px",
                justifyContent: "center",
                marginBottom: "2rem",
              }}
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
                  style={{
                    width: "48px",
                    height: "56px",
                    textAlign: "center",
                    fontSize: "1.5rem",
                    fontWeight: 700,
                    background: PALETTE.inputBg,
                    border: `2px solid ${
                      digit
                        ? PALETTE.inputBorderFocus
                        : PALETTE.inputBorder
                    }`,
                    borderRadius: "12px",
                    color: PALETTE.text,
                    outline: "none",
                    transition: "border-color 0.15s, transform 0.1s",
                    transform: digit ? "scale(1.04)" : "scale(1)",
                    cursor: loading ? "not-allowed" : "text",
                    caretColor: PALETTE.accent,
                  }}
                  onFocus={(e) => {
                    e.target.style.borderColor = PALETTE.inputBorderFocus;
                    e.target.style.boxShadow = `0 0 0 3px rgba(124,58,237,0.15)`;
                  }}
                  onBlur={(e) => {
                    e.target.style.borderColor = digit
                      ? PALETTE.inputBorderFocus
                      : PALETTE.inputBorder;
                    e.target.style.boxShadow = "none";
                  }}
                />
              ))}
            </div>
          </fieldset>

          {/* Submit button (manual) */}
          <button
            type="button"
            onClick={() => allFilled && submitOtp(digits.join(""))}
            disabled={!allFilled || loading}
            style={{
              width: "100%",
              padding: "0.875rem",
              background: !allFilled || loading
                ? "rgba(124,58,237,0.4)"
                : PALETTE.accent,
              color: "#fff",
              border: "none",
              borderRadius: "10px",
              fontSize: "0.95rem",
              fontWeight: 700,
              cursor: !allFilled || loading ? "not-allowed" : "pointer",
              transition: "background 0.15s",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: "0.5rem",
              marginBottom: "1.25rem",
            }}
            onMouseEnter={(e) => {
              if (allFilled && !loading) {
                e.currentTarget.style.background = PALETTE.accentHover;
              }
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background =
                !allFilled || loading ? "rgba(124,58,237,0.4)" : PALETTE.accent;
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
                {t("auth.verifying", "Verifying...")}
              </>
            ) : (
              t("auth.verifyButton", "Verify Code")
            )}
          </button>

          {/* Resend */}
          <p
            style={{
              textAlign: "center",
              color: PALETTE.muted,
              fontSize: "0.875rem",
              margin: 0,
            }}
          >
            {t("auth.didntGetCode", "Didn't get a code?")}{" "}
            {cooldown > 0 ? (
              <span style={{ color: PALETTE.muted }}>
                {t("auth.resendIn", "Resend in {{s}}s", { s: cooldown })}
              </span>
            ) : (
              <button
                type="button"
                onClick={handleResend}
                disabled={resendLoading}
                style={{
                  background: "none",
                  border: "none",
                  cursor: resendLoading ? "wait" : "pointer",
                  color: "#a78bfa",
                  fontWeight: 600,
                  fontSize: "0.875rem",
                  padding: 0,
                  textDecoration: "underline",
                  textUnderlineOffset: "2px",
                }}
              >
                {resendLoading
                  ? t("auth.resending", "Resending...")
                  : t("auth.resendCode", "Resend code")}
              </button>
            )}
          </p>
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
            style={{ color: "#a78bfa", textDecoration: "none", fontWeight: 500 }}
          >
            {t("auth.backToLogin", "Back to Login")}
          </Link>
        </p>
      </motion.div>
    </div>
  );
}
