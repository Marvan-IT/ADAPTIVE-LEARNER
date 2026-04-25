import { useState, useEffect } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { Brain } from "lucide-react";
import { useTranslation } from "react-i18next";
import ConstellationBackground from "./ConstellationBackground";
import LanguageSelector from "../components/LanguageSelector";

// ── Tagline cycle ─────────────────────────────────────────────────────────────
function RotatingTagline() {
  const { t } = useTranslation();

  const taglines = [
    t("auth.tagline1", "Map your knowledge"),
    t("auth.tagline2", "Learn at your pace"),
    t("auth.tagline3", "Master any concept"),
    t("auth.tagline4", "Your journey, your way"),
  ];

  const [index, setIndex] = useState(0);

  useEffect(() => {
    const id = setInterval(() => {
      setIndex((prev) => (prev + 1) % taglines.length);
    }, 5000);
    return () => clearInterval(id);
  }, [taglines.length]);

  return (
    <div className="h-8 overflow-hidden relative">
      <AnimatePresence mode="wait">
        <motion.p
          key={index}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          transition={{ duration: 0.3, ease: "easeOut" }}
          className="text-lg font-medium text-white/90 absolute inset-0"
        >
          {taglines[index]}
        </motion.p>
      </AnimatePresence>
    </div>
  );
}

// ── Logo mark ─────────────────────────────────────────────────────────────────
function LogoMark({ light = false }) {
  return (
    <div className="flex items-center gap-3">
      <Brain
        size={32}
        className={light ? "text-white shrink-0" : "text-[var(--color-primary)] shrink-0"}
        aria-hidden="true"
      />
      <span
        className={
          light
            ? "text-2xl font-extrabold text-white tracking-tight leading-none"
            : "text-2xl font-extrabold text-[var(--color-text)] tracking-tight leading-none"
        }
      >
        Adaptive Learner
      </span>
    </div>
  );
}

// ── Main layout ───────────────────────────────────────────────────────────────
export default function AuthLayout() {
  const location = useLocation();
  const { t, i18n } = useTranslation();

  // Auth screens are always English — student's preferred language syncs
  // from their profile after login (StudentContext). Clears localStorage
  // so refresh stays English; user can still switch via the selector.
  useEffect(() => {
    if (i18n.language !== "en") {
      i18n.changeLanguage("en");
    }
    try {
      localStorage.removeItem("ada_language");
    } catch {
      // ignore storage errors
    }
  }, [i18n]);

  // Tagline rotation
  const taglines = [
    t("auth.tagline1", "Map your knowledge"),
    t("auth.tagline2", "Learn at your pace"),
    t("auth.tagline3", "Master any concept"),
    t("auth.tagline4", "Your journey, your way"),
  ];
  const [taglineIndex, setTaglineIndex] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTaglineIndex((p) => (p + 1) % taglines.length), 5000);
    return () => clearInterval(id);
  }, [taglines.length]);

  return (
    <div className="min-h-screen bg-[var(--color-bg)]">

      {/* ── Left brand panel (desktop only) ────────────────────────────── */}
      <aside
        className="hidden lg:flex lg:w-[45%] lg:fixed lg:inset-y-0 lg:start-0 flex-col items-center justify-center overflow-hidden relative"
        aria-hidden="true"
        style={{
          background: "linear-gradient(135deg, #FDBA74 0%, #F97316 50%, #EA580C 100%)",
        }}
      >
        {/* Constellation fills the full panel */}
        <ConstellationBackground />

        {/* Logo + Tagline — centered together in the panel */}
        <div className="relative z-10 flex flex-col items-center gap-3">
          <Brain size={48} className="text-white" aria-hidden="true" />
          <span className="text-4xl font-extrabold text-white tracking-tight" style={{ fontFamily: "'Outfit', sans-serif" }}>
            Adaptive Learner
          </span>
          <div className="h-7 overflow-hidden relative w-full text-center">
            <AnimatePresence mode="wait">
              <motion.p
                key={taglineIndex}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                transition={{ duration: 0.3, ease: "easeOut" }}
                className="text-lg font-medium text-white/80 absolute inset-0"
              >
                {taglines[taglineIndex]}
              </motion.p>
            </AnimatePresence>
          </div>
        </div>
      </aside>

      {/* ── Right content panel ─────────────────────────────────────────── */}
      <div className="lg:fixed lg:inset-y-0 lg:end-0 lg:w-[55%] flex flex-col min-h-screen bg-[var(--color-bg)] overflow-y-auto overflow-x-hidden z-10">

        {/* Mobile top bar — logo left, language right */}
        <header className="flex lg:hidden items-center justify-between px-6 pt-6">
          <LogoMark />
          <LanguageSelector compact />
        </header>

        {/* Desktop top bar — language only, end-aligned */}
        <div className="hidden lg:flex items-center justify-end p-6">
          <LanguageSelector compact />
        </div>

        {/* Centered form area */}
        <main className="flex-1 flex items-center justify-center px-6 py-6 lg:px-12 lg:py-6">
          <div className="w-full max-w-[420px]">
            <AnimatePresence mode="wait">
              <motion.div
                key={location.pathname}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                transition={{ duration: 0.2, ease: "easeOut" }}
              >
                <Outlet />
              </motion.div>
            </AnimatePresence>
          </div>
        </main>
      </div>

    </div>
  );
}
