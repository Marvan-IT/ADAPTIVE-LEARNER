import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "framer-motion";
import { useTranslation } from "react-i18next";

/**
 * Full-screen loading overlay shown while a language change API call is in-flight.
 *
 * Props
 * -----
 * open           – boolean  – show/hide the overlay
 * targetLanguage – object   – { name, native, flag, code }
 * apiDone        – boolean  – signals the backend call completed; allows progress past 85 %
 * onComplete     – function – called when the exit animation finishes (triggers cleanup)
 */
export default function LanguageChangeOverlay({ open, targetLanguage, apiDone, onComplete }) {
  const { t } = useTranslation();

  // 0-100 progress value driven by the interval below
  const [progress, setProgress] = useState(0);
  const intervalRef = useRef(null);
  // Track whether we already fired onComplete so we don't call it twice
  const completedRef = useRef(false);
  // Mirror apiDone into a ref so the interval closure always reads the latest value
  const apiDoneRef = useRef(apiDone);

  useEffect(() => {
    apiDoneRef.current = apiDone;
  }, [apiDone]);

  // Reset and start progress whenever the overlay opens
  useEffect(() => {
    if (!open) {
      // Overlay is closing – reset for next use
      setProgress(0);
      completedRef.current = false;
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      return;
    }

    setProgress(0);
    completedRef.current = false;

    // Tick every 30 ms; speed varies by phase
    intervalRef.current = setInterval(() => {
      setProgress((prev) => {
        // Phase 1: 0 → 40 at ~1.5 units/tick  (~800 ms)
        if (prev < 40) {
          return Math.min(prev + 1.5, 40);
        }

        // Phase 2: 40 → 85 at ~0.9 units/tick  (~1500 ms)
        if (prev < 85) {
          return Math.min(prev + 0.9, 85);
        }

        // Stall at 85 until the API is done
        if (!apiDoneRef.current) {
          return prev;
        }

        // Phase 3: 85 → 100 at ~1.125 units/tick (~400 ms)
        if (prev < 100) {
          const next = Math.min(prev + 1.125, 100);
          if (next >= 100 && !completedRef.current) {
            completedRef.current = true;
            // Small delay so the student can see "Done!" before the overlay hides
            setTimeout(() => onComplete?.(), 500);
          }
          return next;
        }

        return prev; // already at 100
      });
    }, 30);

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
    // We intentionally omit onComplete from deps – it would recreate the interval on
    // every render. completedRef guards against duplicate calls.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // Derive step label from current progress
  const stepKey =
    progress >= 85
      ? "lang.done"
      : progress >= 40
        ? "lang.translatingContent"
        : "lang.updatingLanguage";

  const overlay = (
    <AnimatePresence>
      {open && targetLanguage && (
        <motion.div
          key="lang-overlay-backdrop"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2, ease: "easeInOut" }}
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 10000,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            backdropFilter: "blur(8px)",
            WebkitBackdropFilter: "blur(8px)",
            backgroundColor: "rgba(15, 23, 42, 0.55)",
          }}
        >
          {/* Card */}
          <motion.div
            key="lang-overlay-card"
            initial={{ opacity: 0, scale: 0.88, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.92, y: -12 }}
            transition={{ duration: 0.28, ease: [0.34, 1.56, 0.64, 1] }}
            style={{
              width: "380px",
              maxWidth: "calc(100vw - 32px)",
              backgroundColor: "#FFFFFF",
              borderRadius: "20px",
              boxShadow: "0 25px 60px rgba(0,0,0,0.15), 0 8px 24px rgba(0,0,0,0.08)",
              padding: "36px 32px 32px",
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: "0px",
              fontFamily: "'Outfit', sans-serif",
              userSelect: "none",
            }}
          >
            {/* Flag */}
            <div
              style={{
                fontSize: "64px",
                lineHeight: 1,
                marginBottom: "16px",
                filter: "drop-shadow(0 4px 8px rgba(0,0,0,0.12))",
              }}
              aria-hidden="true"
            >
              {targetLanguage.flag}
            </div>

            {/* Native name */}
            <div
              style={{
                fontSize: "22px",
                fontWeight: 700,
                color: "#0F172A",
                lineHeight: 1.2,
                marginBottom: "4px",
                textAlign: "center",
              }}
            >
              {targetLanguage.native}
            </div>

            {/* English name */}
            <div
              style={{
                fontSize: "14px",
                fontWeight: 500,
                color: "#94A3B8",
                marginBottom: "28px",
                textAlign: "center",
                letterSpacing: "0.01em",
              }}
            >
              {targetLanguage.name}
            </div>

            {/* Step label with fade transition */}
            <div
              style={{
                height: "20px",
                marginBottom: "12px",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                width: "100%",
                overflow: "hidden",
              }}
            >
              <AnimatePresence mode="wait">
                <motion.span
                  key={stepKey}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -6 }}
                  transition={{ duration: 0.18, ease: "easeInOut" }}
                  style={{
                    fontSize: "13px",
                    fontWeight: 600,
                    color: "#64748B",
                    letterSpacing: "0.01em",
                    textAlign: "center",
                  }}
                >
                  {t(stepKey)}
                </motion.span>
              </AnimatePresence>
            </div>

            {/* Progress bar */}
            <div
              style={{
                width: "100%",
                height: "8px",
                borderRadius: "999px",
                backgroundColor: "#F1F5F9",
                overflow: "hidden",
                marginBottom: "10px",
              }}
              role="progressbar"
              aria-valuenow={Math.round(progress)}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label={t(stepKey)}
            >
              <motion.div
                style={{
                  height: "100%",
                  borderRadius: "999px",
                  background: "linear-gradient(90deg, #F97316, #FB923C)",
                  transformOrigin: "left center",
                }}
                animate={{ width: `${progress}%` }}
                transition={{ duration: 0.25, ease: "easeOut" }}
              />
            </div>

            {/* Percentage */}
            <div
              style={{
                fontSize: "12px",
                fontWeight: 500,
                color: "#94A3B8",
                textAlign: "center",
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {Math.round(progress)}%
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );

  return createPortal(overlay, document.body);
}
