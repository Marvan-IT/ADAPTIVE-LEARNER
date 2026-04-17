import { useState, useRef, useEffect, useCallback } from "react";
import { useNavigate, useLocation, Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";
import { AlertCircle, CheckCircle2, Mail } from "lucide-react";
import { verifyOtp, resendOtp } from "../api/auth";
import { useAuth } from "../context/AuthContext";

const RESEND_COOLDOWN = 60;

// ── Shared style tokens ────────────────────────────────────────────────────────
const card = {
  background: "#fff",
  borderRadius: 20,
  padding: "32px 28px",
  boxShadow: "0 4px 24px rgba(0,0,0,0.07)",
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

const successBannerStyle = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  borderRadius: 12,
  padding: "12px 16px",
  marginBottom: 20,
  fontSize: 14,
  color: "#16A34A",
  background: "rgba(34,197,94,0.06)",
  border: "1px solid rgba(34,197,94,0.2)",
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
  marginBottom: 12,
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
};

// Per-digit input style based on state
const getDigitStyle = (digit, isFocused, isDisabled) => ({
  width: 48,
  height: 54,
  textAlign: "center",
  fontSize: 22,
  fontWeight: 700,
  background: "#F8FAFC",
  border: isFocused
    ? "1.5px solid #F97316"
    : digit
    ? "1.5px solid rgba(249,115,22,0.5)"
    : "1.5px solid #E2E8F0",
  borderRadius: 12,
  color: "#1E293B",
  outline: "none",
  transition: "all 0.2s",
  boxShadow: isFocused ? "0 0 0 3px rgba(249,115,22,0.12)" : "none",
  cursor: isDisabled ? "not-allowed" : "text",
  caretColor: "#F97316",
  boxSizing: "border-box",
});

// ── Component ──────────────────────────────────────────────────────────────────
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
  const [focusedIndex, setFocusedIndex] = useState(null);

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
      <div style={card}>
        {/* Animated mail icon + heading */}
        <div style={{ textAlign: "center", marginBottom: 20 }}>
          <motion.div
            animate={{ y: [0, -6, 0] }}
            transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
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
          </motion.div>
          <h1
            style={{
              fontSize: 26,
              fontWeight: 800,
              color: "#1E293B",
              margin: "0 0 4px",
            }}
          >
            {t("auth.checkEmail", "Check your email!")}
          </h1>
          <p style={{ fontSize: 14, color: "#94A3B8", margin: 0 }}>
            {t("auth.otpSentTo", "We sent a 6-digit code to")}{" "}
            <span style={{ fontWeight: 600, color: "#1E293B" }}>{email}</span>
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

        {/* Success banner */}
        {successMsg && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            style={successBannerStyle}
          >
            <CheckCircle2 size={16} aria-hidden="true" />
            {successMsg}
          </motion.div>
        )}

        {/* 6-digit OTP inputs */}
        <fieldset
          style={{ border: "none", padding: 0, margin: 0 }}
          aria-label={t("auth.otpFieldset", "6-digit verification code")}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "center",
              gap: 10,
              marginBottom: 24,
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
                onFocus={() => setFocusedIndex(index)}
                onBlur={() => setFocusedIndex(null)}
                aria-label={t("auth.otpDigitN", { n: index + 1 }, `Digit ${index + 1}`)}
                disabled={loading}
                autoFocus={index === 0}
                style={getDigitStyle(digit, focusedIndex === index, loading)}
              />
            ))}
          </div>
        </fieldset>

        {/* Verify button */}
        <button
          type="button"
          disabled={!allFilled || loading}
          onClick={() => allFilled && submitOtp(digits.join(""))}
          style={getButtonStyle(allFilled && !loading)}
        >
          {loading
            ? t("auth.verifying", "Verifying...")
            : t("auth.verifyButton", "Verify Code")}
        </button>

        {/* Resend */}
        <p style={{ textAlign: "center", fontSize: 13, color: "#64748B", margin: 0 }}>
          {t("auth.didntGetCode", "Didn't get a code?")}{" "}
          {cooldown > 0 ? (
            <span style={{ color: "#94A3B8" }}>
              {t("auth.resendIn", "Resend in {{s}}s", { s: cooldown })}
            </span>
          ) : (
            <button
              type="button"
              onClick={handleResend}
              disabled={resendLoading}
              style={{
                background: "transparent",
                border: "none",
                padding: 0,
                color: "#F97316",
                fontWeight: 600,
                fontSize: 13,
                textDecoration: "underline",
                textUnderlineOffset: 2,
                cursor: resendLoading ? "wait" : "pointer",
              }}
            >
              {resendLoading
                ? t("auth.resending", "Resending...")
                : t("auth.resendCode", "Resend code")}
            </button>
          )}
        </p>
      </div>

      {/* Back to login */}
      <p style={bottomLink}>
        <Link to="/login" style={orangeLink}>
          {t("auth.backToLogin", "Back to Login")}
        </Link>
      </p>
    </>
  );
}
