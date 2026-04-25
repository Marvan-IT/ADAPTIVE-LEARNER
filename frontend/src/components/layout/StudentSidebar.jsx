import { useState } from "react";
import { NavLink, useNavigate, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";
import {
  Brain, Map, Clock, Trophy, ChevronsLeft, ChevronsRight,
  Flame, LayoutDashboard, Award, Settings, AlertCircle,
} from "lucide-react";
import { useStudent } from "../../context/StudentContext";
import { useAdaptiveStore } from "../../store/adaptiveStore";
import { useSession } from "../../context/SessionContext";
import { Tooltip } from "../ui";
import { cn } from "../ui/lib/utils";

const ACTIVE_PHASES = ["CARDS", "CHECKING", "RECHECKING", "RECHECKING_2", "REMEDIATING", "REMEDIATING_2", "CHUNK_QUESTIONS"];

function buildNavItems(t) {
  return [
    { section: t("nav.learn"), items: [
      { to: "/dashboard", icon: LayoutDashboard, label: t("nav.dashboard", "Dashboard"), iconBg: "#FFF7ED", iconColor: "#F97316" },
      { to: "/map", icon: Map, label: t("nav.conceptMap"), iconBg: "#EFF6FF", iconColor: "#3B82F6" },
    ]},
    { section: t("nav.progress"), items: [
      { to: "/history", icon: Clock, label: t("nav.history", "History"), iconBg: "#F0FDF4", iconColor: "#22C55E" },
      { to: "/leaderboard", icon: Trophy, label: t("nav.leaderboard", "Leaderboard"), iconBg: "#FAF5FF", iconColor: "#8B5CF6" },
      { to: "/achievements", icon: Award, label: t("nav.achievements", "Achievements"), iconBg: "#FFF1F2", iconColor: "#F43F5E" },
    ]},
  ];
}

export default function StudentSidebar({ collapsed, onToggleCollapse }) {
  const { t } = useTranslation();
  const { student, isHydrated } = useStudent();
  const navigate = useNavigate();
  const location = useLocation();
  const { phase, reset: resetSession } = useSession();
  const isLessonActive = ACTIVE_PHASES.includes(phase);
  const xp = useAdaptiveStore((s) => s.xp);
  const level = useAdaptiveStore((s) => s.level);
  const dailyStreak = useAdaptiveStore((s) => s.dailyStreak);
  const displayName = student?.display_name || "Student";
  const NAV_ITEMS = buildNavItems(t);

  const [leaveTarget, setLeaveTarget] = useState(null);

  return (
    <>
    {/* Leave section confirmation modal */}
    {leaveTarget && (
      <div
        style={{ position: "fixed", inset: 0, zIndex: 9999, display: "flex", alignItems: "center", justifyContent: "center", backgroundColor: "rgba(0,0,0,0.5)" }}
        onClick={() => setLeaveTarget(null)}
      >
        <div
          style={{ backgroundColor: "#FFFFFF", borderRadius: "16px", padding: "24px", maxWidth: "400px", width: "90%", boxShadow: "0 8px 32px rgba(0,0,0,0.15)", border: "1px solid #E2E8F0" }}
          onClick={(e) => e.stopPropagation()}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "12px" }}>
            <AlertCircle size={22} color="#F59E0B" />
            <h3 style={{ margin: 0, fontSize: "16px", fontWeight: 700, color: "#0F172A" }}>
              {t("confirm.leaveSection")}
            </h3>
          </div>
          <p style={{ margin: "0 0 20px", fontSize: "14px", color: "#64748B", lineHeight: 1.5 }}>
            {t("confirm.leaveSectionMessage")}
          </p>
          <div style={{ display: "flex", gap: "10px", justifyContent: "flex-end" }}>
            <button
              onClick={() => setLeaveTarget(null)}
              style={{ padding: "8px 16px", borderRadius: "8px", border: "1px solid #E2E8F0", backgroundColor: "transparent", color: "#64748B", fontSize: "14px", fontWeight: 600, cursor: "pointer" }}
            >
              {t("confirm.cancel")}
            </button>
            <button
              onClick={() => {
                if (isLessonActive) resetSession();
                navigate(leaveTarget);
                setLeaveTarget(null);
              }}
              style={{ padding: "8px 16px", borderRadius: "8px", border: "none", backgroundColor: "#EF4444", color: "#FFFFFF", fontSize: "14px", fontWeight: 600, cursor: "pointer" }}
            >
              {t("common.leave", "Leave")}
            </button>
          </div>
        </div>
      </div>
    )}
    <motion.aside
      animate={{ width: collapsed ? 72 : 250 }}
      transition={{ type: "spring", stiffness: 300, damping: 30 }}
      style={{
        height: "100vh", display: "flex", flexDirection: "column",
        background: "#fff", borderRight: "1px solid #e2e8f0",
        overflow: "visible", flexShrink: 0, position: "relative", zIndex: 10,
      }}
    >
      {/* Collapse toggle — floating circle on edge */}
      <button
        onClick={onToggleCollapse}
        style={{
          position: "absolute", top: "50%", right: "-14px", transform: "translateY(-50%)",
          width: 28, height: 28, borderRadius: "50%",
          border: "1.5px solid #e2e8f0", background: "#fff",
          cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center",
          zIndex: 30, boxShadow: "0 2px 6px rgba(0,0,0,0.08)",
        }}
      >
        {collapsed ? <ChevronsRight size={14} color="#64748b" /> : <ChevronsLeft size={14} color="#64748b" />}
      </button>

      {/* Logo */}
      <div onClick={() => navigate("/map")} style={{
        display: "flex", alignItems: "center", gap: "12px", cursor: "pointer",
        padding: collapsed ? "28px 0 20px" : "28px 24px 20px",
        justifyContent: collapsed ? "center" : "flex-start",
      }}>
        <div style={{
          width: 38, height: 38, borderRadius: "50%",
          background: "linear-gradient(135deg, #fb923c, #ea580c)",
          display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
        }}>
          <Brain size={18} color="#fff" />
        </div>
        {!collapsed && (
          <span style={{ fontSize: "17px", fontWeight: 800, color: "#0f172a", fontFamily: "'Outfit', sans-serif" }}>
            {t("app.title")}
          </span>
        )}
      </div>

      {/* Profile Card */}
      {!collapsed ? (
        <div style={{
          margin: "0 20px 16px", padding: "18px",
          background: "linear-gradient(135deg, #fff7ed, #ffedd5)",
          borderRadius: "18px",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: "14px" }}>
            <div style={{
              width: 46, height: 46, borderRadius: "50%",
              background: "linear-gradient(135deg, #fb923c, #ea580c)",
              display: "flex", alignItems: "center", justifyContent: "center",
              color: "#fff", fontWeight: 700, fontSize: "20px", flexShrink: 0,
            }}>
              {displayName.charAt(0).toUpperCase()}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: "16px", fontWeight: 600, color: "#0f172a", fontFamily: "'Outfit', sans-serif", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {displayName}
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "6px", marginTop: "4px" }}>
                <div style={{
                  width: 22, height: 22, borderRadius: "50%",
                  background: "linear-gradient(135deg, #fb923c, #ea580c)",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  color: "#fff", fontSize: "10px", fontWeight: 700,
                }}>
                  {isHydrated ? level : "—"}
                </div>
                <span style={{ fontSize: "13px", color: "#64748b" }}>{isHydrated ? t("nav.level", { level }) : "—"}</span>
              </div>
            </div>
          </div>
          <div style={{ marginTop: "14px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", fontWeight: 600, color: "#94a3b8", marginBottom: "6px" }}>
              <span>{isHydrated ? t("nav.levelShort", { level }) : "—"}</span>
              <span>{isHydrated ? t("nav.xpProgress", { current: xp % 100, max: 100 }) : "—"}</span>
            </div>
            <div style={{ width: "100%", height: "10px", borderRadius: "5px", background: "rgba(251,146,60,0.2)", overflow: "hidden" }}>
              <motion.div
                style={{ height: "100%", borderRadius: "5px", background: "linear-gradient(90deg, #fb923c, #f97316)" }}
                initial={{ width: 0 }} animate={{ width: isHydrated ? `${xp % 100}%` : "0%" }}
                transition={{ type: "spring", stiffness: 100, damping: 20 }}
              />
            </div>
          </div>
          {dailyStreak >= 1 && (
            <div style={{ display: "flex", alignItems: "center", gap: "6px", marginTop: "12px" }}>
              <Flame size={16} color="#f97316" />
              <span style={{ fontSize: "14px", fontWeight: 700, color: "#f97316" }}>{dailyStreak}</span>
              <span style={{ fontSize: "12px", color: "#94a3b8" }}>{t("nav.dayStreak", "day streak")}</span>
            </div>
          )}
        </div>
      ) : (
        <div style={{ display: "flex", justifyContent: "center", padding: "12px 0 16px" }}>
          <Tooltip content={displayName} position="right">
            <div style={{
              width: 44, height: 44, borderRadius: "50%",
              background: "linear-gradient(135deg, #fb923c, #ea580c)",
              display: "flex", alignItems: "center", justifyContent: "center",
              color: "#fff", fontWeight: 700, fontSize: "16px",
            }}>
              {displayName.charAt(0).toUpperCase()}
            </div>
          </Tooltip>
        </div>
      )}

      {/* Navigation — matching admin sidebar spacing */}
      <nav style={{
        flex: 1, padding: collapsed ? "8px 12px" : "0 20px",
        overflowY: "auto",
      }}>
        {NAV_ITEMS.map((group) => (
          <div key={group.section} style={{ marginBottom: collapsed ? "8px" : "0" }}>
            {!collapsed && (
              <div style={{
                padding: "24px 8px 10px", fontSize: "11px", fontWeight: 700,
                textTransform: "uppercase", letterSpacing: "1px", color: "#94a3b8",
              }}>
                {group.section}
              </div>
            )}

            {group.items.map(({ to, icon: Icon, label, iconBg, iconColor }) => {
              const navItem = (
                <NavLink key={to} to={to}
                  style={{ textDecoration: "none" }}
                  onClick={(e) => {
                    if (isLessonActive && location.pathname.startsWith("/learn/")) {
                      e.preventDefault();
                      setLeaveTarget(to);
                    }
                  }}
                  className={({ isActive }) => cn(
                    "flex items-center rounded-2xl font-medium transition-colors",
                    collapsed ? "justify-center" : "",
                    isActive ? "bg-orange-50 text-[#F97316]" : "text-[#475569] hover:bg-slate-50",
                    !collapsed && isActive && "border-s-[3px] border-[#F97316]",
                    !collapsed && !isActive && "border-s-[3px] border-transparent",
                  )}
                >
                  {({ isActive }) => (
                    <div style={{
                      display: "flex", alignItems: "center",
                      gap: collapsed ? "0" : "14px",
                      padding: collapsed ? "8px 0" : "8px 12px",
                      width: "100%",
                      justifyContent: collapsed ? "center" : "flex-start",
                    }}>
                      <div style={{
                        width: 30, height: 30, borderRadius: "50%",
                        display: "flex", alignItems: "center", justifyContent: "center",
                        flexShrink: 0,
                        backgroundColor: isActive ? "#FFF7ED" : iconBg,
                        color: isActive ? "#F97316" : iconColor,
                        transition: "all 0.15s",
                      }}>
                        <Icon size={15} />
                      </div>
                      {!collapsed && (
                        <span style={{ fontSize: "13px", fontFamily: "'DM Sans', sans-serif" }}>{label}</span>
                      )}
                    </div>
                  )}
                </NavLink>
              );
              return collapsed
                ? <Tooltip key={to} content={label} position="right">{navItem}</Tooltip>
                : navItem;
            })}
          </div>
        ))}
      </nav>

      {/* Bottom: Settings */}
      <div style={{
        padding: collapsed ? "16px 12px" : "16px 20px",
        borderTop: "1px solid #f1f5f9",
      }}>
        {(() => {
          const settingsItem = (
            <NavLink to="/settings"
              style={{ textDecoration: "none" }}
              onClick={(e) => {
                if (isLessonActive && location.pathname.startsWith("/learn/")) {
                  e.preventDefault();
                  setLeaveTarget("/settings");
                }
              }}
              className={({ isActive }) => cn(
                "flex items-center rounded-2xl font-medium transition-colors",
                collapsed ? "justify-center" : "",
                isActive ? "bg-orange-50 text-[#F97316]" : "text-[#475569] hover:bg-slate-50",
                !collapsed && isActive && "border-s-[3px] border-[#F97316]",
                !collapsed && !isActive && "border-s-[3px] border-transparent",
              )}
            >
              {({ isActive }) => (
                <div style={{
                  display: "flex", alignItems: "center",
                  gap: collapsed ? "0" : "14px",
                  padding: collapsed ? "8px 0" : "8px 12px",
                  width: "100%",
                  justifyContent: collapsed ? "center" : "flex-start",
                }}>
                  <div style={{
                    width: 30, height: 30, borderRadius: "50%",
                    display: "flex", alignItems: "center", justifyContent: "center",
                    flexShrink: 0,
                    backgroundColor: isActive ? "#FFF7ED" : "#F1F5F9",
                    color: isActive ? "#F97316" : "#64748B",
                    transition: "all 0.15s",
                  }}>
                    <Settings size={15} />
                  </div>
                  {!collapsed && (
                    <span style={{ fontSize: "13px", fontFamily: "'DM Sans', sans-serif" }}>{t("nav.settings")}</span>
                  )}
                </div>
              )}
            </NavLink>
          );
          return collapsed
            ? <Tooltip content={t("nav.settings")} position="right">{settingsItem}</Tooltip>
            : settingsItem;
        })()}
      </div>
    </motion.aside>
    </>
  );
}
