import { useState, useRef, useEffect } from "react";
import { Outlet, Navigate, useNavigate, Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useStudent } from "../../context/StudentContext";
import StyleSwitcher from "./StyleSwitcher";
import LanguageSelector from "../LanguageSelector";
import { Brain, Map, LogOut, ChevronDown, User, BookOpen } from "lucide-react";
import { useAdaptiveStore } from "../../store/adaptiveStore";
import LevelBadge from "../game/LevelBadge";
import StreakMeter from "../game/StreakMeter";
import AdaptiveModeIndicator from "../game/AdaptiveModeIndicator";

export default function AppShell() {
  const { t } = useTranslation();
  const { student, logout, loading } = useStudent();
  const navigate = useNavigate();
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const dropdownRef = useRef(null);
  const xp = useAdaptiveStore((s) => s.xp);
  const level = useAdaptiveStore((s) => s.level);

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  if (loading) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: "100vh" }}>
        <div style={{
          width: "36px", height: "36px",
          border: "3px solid var(--color-primary)",
          borderTopColor: "transparent",
          borderRadius: "50%",
          animation: "spin 0.8s linear infinite",
        }} aria-hidden="true" />
      </div>
    );
  }

  if (!student) {
    return <Navigate to="/" />;
  }

  return (
    <div style={{ minHeight: "100vh" }}>
      {/* Nav Bar */}
      <nav
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "0 1.5rem",
          height: "64px",
          backgroundColor: "color-mix(in srgb, var(--color-surface) 88%, transparent)",
          backdropFilter: "blur(12px)",
          WebkitBackdropFilter: "blur(12px)",
          borderBottom: "1.5px solid var(--color-border)",
          position: "sticky",
          top: 0,
          zIndex: 50,
          boxShadow: "var(--shadow-sm)",
        }}
      >
        {/* Left: Logo + Map button */}
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <button
            onClick={() => navigate("/map")}
            style={{
              display: "flex",
              alignItems: "center",
              gap: "0.5rem",
              background: "none",
              border: "none",
              cursor: "pointer",
              fontWeight: 800,
              fontSize: "1.25rem",
              color: "var(--color-primary)",
              fontFamily: "inherit",
              padding: "0.25rem",
            }}
            aria-label="Go to concept map"
          >
            <Brain size={26} aria-hidden="true" />
            {t("app.title")}
          </button>

          {/* Map icon button */}
          <button
            onClick={() => navigate("/map")}
            style={{
              display: "flex",
              alignItems: "center",
              gap: "0.3rem",
              padding: "0.35rem 0.65rem",
              background: "var(--color-primary-light)",
              border: "none",
              borderRadius: "var(--radius-full)",
              color: "var(--color-primary)",
              cursor: "pointer",
              fontFamily: "inherit",
              fontSize: "0.8rem",
              fontWeight: 700,
              transition: "background var(--motion-fast)",
            }}
            onMouseEnter={(e) => (e.currentTarget.style.filter = "brightness(0.95)")}
            onMouseLeave={(e) => (e.currentTarget.style.filter = "brightness(1)")}
            aria-label="Concept Map"
          >
            <Map size={14} aria-hidden="true" />
            {t("nav.conceptMap")}
          </button>
        </div>

        {/* Center: XP + Level HUD */}
        <div style={{ display: "flex", alignItems: "center", gap: "0.6rem", flex: 1, justifyContent: "center", maxWidth: "360px" }}>
          <LevelBadge size={36} />
          <div style={{ flex: 1 }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.65rem", color: "var(--color-text-muted)", fontWeight: 600, marginBottom: "3px" }}>
              <span>Lv.{level}</span>
              <span>{xp % 100}/100 XP</span>
            </div>
            <div style={{ height: "6px", borderRadius: "9999px", background: "var(--color-border)", overflow: "hidden" }}>
              <div style={{
                height: "100%",
                width: `${xp % 100}%`,
                borderRadius: "9999px",
                background: "linear-gradient(90deg, var(--color-primary), var(--xp-gold))",
                transition: "width 0.5s var(--spring-soft)",
              }} />
            </div>
          </div>
          <AdaptiveModeIndicator compact />
        </div>

        {/* Right: Streak + Student dropdown */}
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <StreakMeter compact />

          <div ref={dropdownRef} style={{ position: "relative" }}>
            <button
              onClick={() => setDropdownOpen((v) => !v)}
              aria-expanded={dropdownOpen}
              aria-haspopup="true"
              style={{
                display: "flex",
                alignItems: "center",
                gap: "0.4rem",
                padding: "0.4rem 0.75rem",
                borderRadius: "var(--radius-full)",
                border: "1.5px solid var(--color-border)",
                backgroundColor: "var(--color-surface)",
                color: "var(--color-text)",
                cursor: "pointer",
                fontFamily: "inherit",
                fontSize: "0.875rem",
                fontWeight: 600,
                transition: "border-color var(--motion-fast)",
              }}
              onMouseEnter={(e) => (e.currentTarget.style.borderColor = "var(--color-primary)")}
              onMouseLeave={(e) => (e.currentTarget.style.borderColor = "var(--color-border)")}
            >
              <User size={15} aria-hidden="true" />
              {student.display_name}
              <ChevronDown
                size={14}
                aria-hidden="true"
                style={{ transition: "transform var(--motion-fast)", transform: dropdownOpen ? "rotate(180deg)" : "rotate(0deg)" }}
              />
            </button>

            {/* Dropdown */}
            {dropdownOpen && (
              <div
                style={{
                  position: "absolute",
                  top: "calc(100% + 8px)",
                  right: 0,
                  minWidth: "220px",
                  backgroundColor: "var(--color-surface)",
                  borderRadius: "var(--radius-lg)",
                  border: "1.5px solid var(--color-border)",
                  boxShadow: "var(--shadow-lg)",
                  padding: "0.75rem",
                  zIndex: 100,
                  animation: "fade-up 0.15s ease-out",
                }}
              >
                {/* Learning History link */}
                <Link
                  to="/history"
                  onClick={() => setDropdownOpen(false)}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "0.4rem",
                    width: "100%",
                    padding: "0.5rem 0.5rem",
                    borderRadius: "var(--radius-sm)",
                    border: "none",
                    backgroundColor: "transparent",
                    color: "var(--color-text)",
                    fontSize: "0.875rem",
                    fontWeight: 600,
                    cursor: "pointer",
                    fontFamily: "inherit",
                    textDecoration: "none",
                    transition: "background var(--motion-fast)",
                    marginBottom: "0.25rem",
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "var(--color-primary-light)")}
                  onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "transparent")}
                >
                  <BookOpen size={14} aria-hidden="true" />
                  {t("nav.learningHistory") || "Learning History"}
                </Link>

                <hr style={{ border: "none", borderTop: "1px solid var(--color-border)", margin: "0.25rem 0 0.5rem" }} />

                <div style={{
                  fontSize: "0.7rem", fontWeight: 700,
                  color: "var(--color-text-muted)",
                  textTransform: "uppercase",
                  letterSpacing: "0.05em",
                  marginBottom: "0.5rem",
                  paddingLeft: "0.25rem",
                }}>
                  Language
                </div>
                <div style={{ marginBottom: "0.75rem" }}>
                  <LanguageSelector compact />
                </div>

                <div style={{
                  fontSize: "0.7rem", fontWeight: 700,
                  color: "var(--color-text-muted)",
                  textTransform: "uppercase",
                  letterSpacing: "0.05em",
                  marginBottom: "0.5rem",
                  paddingLeft: "0.25rem",
                }}>
                  Theme
                </div>
                <div style={{ marginBottom: "0.75rem" }}>
                  <StyleSwitcher />
                </div>

                <hr style={{ border: "none", borderTop: "1px solid var(--color-border)", margin: "0.5rem 0" }} />

                <button
                  onClick={() => { logout(); navigate("/"); setDropdownOpen(false); }}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "0.4rem",
                    width: "100%",
                    padding: "0.5rem 0.5rem",
                    borderRadius: "var(--radius-sm)",
                    border: "none",
                    backgroundColor: "transparent",
                    color: "var(--color-danger)",
                    fontSize: "0.875rem",
                    fontWeight: 600,
                    cursor: "pointer",
                    fontFamily: "inherit",
                    textAlign: "left",
                    transition: "background var(--motion-fast)",
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "rgba(239,68,68,0.08)")}
                  onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "transparent")}
                >
                  <LogOut size={14} aria-hidden="true" />
                  {t("nav.switch")}
                </button>
              </div>
            )}
          </div>
        </div>
      </nav>

      {/* Adaptive mode glow line */}
      <div style={{
        height: "2px",
        background: "linear-gradient(90deg, transparent, var(--color-primary), transparent)",
        opacity: 0.4,
      }} />

      {/* Main Content */}
      <main>
        <Outlet />
      </main>
    </div>
  );
}
