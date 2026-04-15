import { useState, useRef, useEffect } from "react";
import { Outlet, Navigate, NavLink, useNavigate, useLocation } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import { useStudent } from "../../context/StudentContext";
import { useAuth } from "../../context/AuthContext";
import { useTheme } from "../../context/ThemeContext";
import LanguageSelector from "../LanguageSelector";
import {
  Brain, Map, BookOpen, LogOut, Trophy,
  ChevronLeft, ChevronRight, Sun, Moon,
} from "lucide-react";
import { useAdaptiveStore } from "../../store/adaptiveStore";
import LevelBadge from "../game/LevelBadge";
import StreakMeter from "../game/StreakMeter";
import StreakMultiplierBadge from "../game/StreakMultiplierBadge";
import AdaptiveModeIndicator from "../game/AdaptiveModeIndicator";

/* ── Sidebar nav link ─────────────────── */
function SidebarLink({ to, icon: Icon, label, collapsed }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        "sidebar-item" + (isActive ? " sidebar-item--active" : "")
      }
      style={{ position: "relative" }}
    >
      {({ isActive }) => (
        <>
          {/* Active accent bar */}
          {isActive && (
            <motion.span
              layoutId="nav-active-bar"
              style={{
                position: "absolute",
                left: 0,
                top: "20%",
                bottom: "20%",
                width: "3px",
                borderRadius: "0 2px 2px 0",
                background: "var(--color-primary)",
              }}
              transition={{ type: "spring", stiffness: 500, damping: 40 }}
            />
          )}
          <Icon size={18} style={{ flexShrink: 0 }} />
          <AnimatePresence>
            {!collapsed && (
              <motion.span
                initial={{ opacity: 0, width: 0 }}
                animate={{ opacity: 1, width: "auto" }}
                exit={{ opacity: 0, width: 0 }}
                transition={{ duration: 0.18 }}
                style={{ overflow: "hidden", whiteSpace: "nowrap" }}
              >
                {label}
              </motion.span>
            )}
          </AnimatePresence>
        </>
      )}
    </NavLink>
  );
}

/* ── XP progress bar ───────────────────── */
function XPBar({ xp, level }) {
  const progress = xp % 100;
  return (
    <div style={{ width: "100%", padding: "0 var(--sp-3)" }}>
      <div style={{
        display: "flex",
        justifyContent: "space-between",
        fontSize: "0.65rem",
        color: "var(--color-sidebar-text)",
        fontWeight: 600,
        marginBottom: "4px",
      }}>
        <span>Lv.{level}</span>
        <span>{progress}/100 XP</span>
      </div>
      <div style={{
        height: "5px",
        borderRadius: "9999px",
        background: "rgba(255,255,255,0.08)",
        overflow: "hidden",
      }}>
        <motion.div
          animate={{ width: `${progress}%` }}
          transition={{ type: "spring", stiffness: 180, damping: 20 }}
          style={{
            height: "100%",
            borderRadius: "9999px",
            background: "linear-gradient(90deg, var(--color-primary), var(--xp-gold))",
          }}
        />
      </div>
    </div>
  );
}

/* ── Main AppShell ─────────────────────── */
export default function AppShell() {
  const { t } = useTranslation();
  const { student, logout, loading: studentLoading } = useStudent();
  const { user, loading: authLoading } = useAuth();
  const { toggleTheme, isDark } = useTheme();
  const navigate = useNavigate();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);
  // Auto-collapse sidebar when entering a learning session
  useEffect(() => {
    if (location.pathname.startsWith("/learn/")) {
      setCollapsed(true);
    }
  }, [location.pathname]);

  const xp    = useAdaptiveStore((s) => s.xp);
  const level = useAdaptiveStore((s) => s.level);

  const loading = studentLoading || authLoading || (!!user?.student_id && !student);

  if (loading) {
    return (
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "center",
        minHeight: "100vh", background: "var(--color-bg)",
      }}>
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

  if (!student) return <Navigate to="/login" replace />;

  const initial = (student.display_name || "S")[0].toUpperCase();

  return (
    <div className="app-layout">
      {/* ── Sidebar ──────────────────────── */}
      <motion.aside
        animate={{ width: collapsed ? "var(--sidebar-collapsed-width)" : "var(--sidebar-width)" }}
        transition={{ type: "spring", stiffness: 300, damping: 30 }}
        style={{
          position: "fixed",
          top: 0,
          left: 0,
          height: "100vh",
          background: "var(--color-sidebar-bg)",
          borderRight: "1px solid var(--color-sidebar-border)",
          display: "flex",
          flexDirection: "column",
          padding: "var(--sp-4) var(--sp-3)",
          zIndex: 40,
          overflow: "hidden",
          flexShrink: 0,
        }}
      >
        {/* Zone 1 — Logo */}
        <div style={{
          display: "flex",
          alignItems: "center",
          gap: "var(--sp-3)",
          marginBottom: "var(--sp-6)",
          paddingLeft: "var(--sp-1)",
          cursor: "pointer",
          flexShrink: 0,
        }} onClick={() => navigate("/map")}>
          <Brain
            size={22}
            color="var(--color-primary)"
            style={{ flexShrink: 0 }}
            aria-hidden="true"
          />
          <AnimatePresence>
            {!collapsed && (
              <motion.span
                initial={{ opacity: 0, width: 0 }}
                animate={{ opacity: 1, width: "auto" }}
                exit={{ opacity: 0, width: 0 }}
                transition={{ duration: 0.18 }}
                style={{
                  fontWeight: 800,
                  fontSize: "1.15rem",
                  color: "#fff",
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  letterSpacing: "-0.01em",
                }}
              >
                {t("app.title")}
              </motion.span>
            )}
          </AnimatePresence>
        </div>

        {/* Zone 2 — Nav links */}
        <nav style={{ display: "flex", flexDirection: "column", gap: "var(--sp-1)", marginBottom: "var(--sp-6)", flexShrink: 0 }}>
          <SidebarLink to="/map"     icon={Map}      label={t("nav.conceptMap")}      collapsed={collapsed} />
          <SidebarLink to="/history" icon={BookOpen}  label={t("nav.learningHistory") || "Learning History"} collapsed={collapsed} />
          <SidebarLink to="/leaderboard" icon={Trophy} label={t("leaderboard.title", "Leaderboard")} collapsed={collapsed} />
        </nav>

        {/* Divider */}
        <div style={{ height: "1px", background: "var(--color-sidebar-border)", marginBottom: "var(--sp-4)", flexShrink: 0 }} />

        {/* Zone 3 — Gamification HUD */}
        <div style={{
          display: "flex",
          flexDirection: "column",
          gap: "var(--sp-3)",
          marginBottom: "var(--sp-4)",
          alignItems: collapsed ? "center" : "flex-start",
          flexShrink: 0,
        }}>
          <div style={{ paddingLeft: collapsed ? 0 : "var(--sp-1)" }}>
            <LevelBadge size={32} />
          </div>
          <AnimatePresence>
            {!collapsed && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
                style={{ width: "100%" }}
              >
                <XPBar xp={xp} level={level} />
              </motion.div>
            )}
          </AnimatePresence>
          <div style={{
            display: "flex",
            alignItems: "center",
            gap: "var(--sp-2)",
            paddingLeft: collapsed ? 0 : "var(--sp-1)",
          }}>
            <StreakMeter compact />
            <StreakMultiplierBadge />
            {!collapsed && <AdaptiveModeIndicator compact />}
          </div>
        </div>

        {/* Divider */}
        <div style={{ height: "1px", background: "var(--color-sidebar-border)", marginBottom: "var(--sp-4)", flexShrink: 0 }} />

        {/* Bottom zone — pinned */}
        <div style={{
          marginTop: "auto",
          display: "flex",
          flexDirection: "column",
          gap: "var(--sp-2)",
          flexShrink: 0,
        }}>
          {/* Student avatar + name */}
          <div style={{
            display: "flex",
            alignItems: "center",
            gap: "var(--sp-2)",
            padding: "var(--sp-2) var(--sp-1)",
          }}>
            <div style={{
              width: "28px", height: "28px",
              borderRadius: "50%",
              background: "linear-gradient(135deg, var(--color-primary), var(--color-accent))",
              display: "flex", alignItems: "center", justifyContent: "center",
              color: "#fff", fontWeight: 800, fontSize: "0.75rem",
              flexShrink: 0,
            }}>
              {initial}
            </div>
            <AnimatePresence>
              {!collapsed && (
                <motion.span
                  initial={{ opacity: 0, width: 0 }}
                  animate={{ opacity: 1, width: "auto" }}
                  exit={{ opacity: 0, width: 0 }}
                  transition={{ duration: 0.18 }}
                  style={{
                    fontSize: "0.8rem",
                    fontWeight: 600,
                    color: "var(--color-sidebar-text-active)",
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    maxWidth: "120px",
                    textOverflow: "ellipsis",
                  }}
                >
                  {student.display_name}
                </motion.span>
              )}
            </AnimatePresence>
          </div>

          {/* Language selector */}
          <div style={{ paddingLeft: collapsed ? 0 : "var(--sp-1)", display: "flex", justifyContent: collapsed ? "center" : "flex-start" }}>
            <LanguageSelector compact />
          </div>

          {/* Dark/light toggle */}
          <button
            onClick={toggleTheme}
            title={t("nav.themeToggle") || "Toggle theme"}
            className="sidebar-item"
            style={{ justifyContent: collapsed ? "center" : "flex-start" }}
          >
            {isDark
              ? <Sun size={16} style={{ flexShrink: 0 }} />
              : <Moon size={16} style={{ flexShrink: 0 }} />}
            <AnimatePresence>
              {!collapsed && (
                <motion.span
                  initial={{ opacity: 0, width: 0 }}
                  animate={{ opacity: 1, width: "auto" }}
                  exit={{ opacity: 0, width: 0 }}
                  transition={{ duration: 0.18 }}
                  style={{ overflow: "hidden", whiteSpace: "nowrap" }}
                >
                  {isDark ? t("nav.lightMode", "Light mode") : t("nav.darkMode", "Dark mode")}
                </motion.span>
              )}
            </AnimatePresence>
          </button>

          {/* Collapse toggle */}
          <button
            onClick={() => setCollapsed((v) => !v)}
            title={collapsed ? (t("nav.expand") || "Expand sidebar") : (t("nav.collapse") || "Collapse sidebar")}
            className="sidebar-item"
            style={{ justifyContent: collapsed ? "center" : "flex-start" }}
          >
            {collapsed
              ? <ChevronRight size={16} style={{ flexShrink: 0 }} />
              : <ChevronLeft size={16} style={{ flexShrink: 0 }} />}
            <AnimatePresence>
              {!collapsed && (
                <motion.span
                  initial={{ opacity: 0, width: 0 }}
                  animate={{ opacity: 1, width: "auto" }}
                  exit={{ opacity: 0, width: 0 }}
                  transition={{ duration: 0.18 }}
                  style={{ overflow: "hidden", whiteSpace: "nowrap" }}
                >
                  {t("nav.collapse") || "Collapse"}
                </motion.span>
              )}
            </AnimatePresence>
          </button>

          {/* Sign out */}
          <button
            onClick={async () => { await logout(); navigate("/login"); }}
            className="sidebar-item"
            style={{ color: "var(--color-danger)", justifyContent: collapsed ? "center" : "flex-start" }}
          >
            <LogOut size={16} style={{ flexShrink: 0 }} />
            <AnimatePresence>
              {!collapsed && (
                <motion.span
                  initial={{ opacity: 0, width: 0 }}
                  animate={{ opacity: 1, width: "auto" }}
                  exit={{ opacity: 0, width: 0 }}
                  transition={{ duration: 0.18 }}
                  style={{ overflow: "hidden", whiteSpace: "nowrap" }}
                >
                  {t("nav.logout", "Logout")}
                </motion.span>
              )}
            </AnimatePresence>
          </button>
        </div>
      </motion.aside>

      {/* ── Main content ─────────────────── */}
      <main
        className={collapsed ? "app-main app-main--collapsed" : "app-main"}
        style={{ minHeight: "100vh" }}
      >
        <AnimatePresence mode="wait">
          <motion.div
            key={location.pathname}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.18, ease: "easeOut" }}
            style={{ minHeight: "100vh" }}
          >
            <Outlet />
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
  );
}
