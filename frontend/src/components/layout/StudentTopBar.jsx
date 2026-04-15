import { useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Sun, Moon, ArrowLeft } from "lucide-react";
import { useTheme } from "../../context/ThemeContext";
import { useStudent } from "../../context/StudentContext";
import { Breadcrumb, Avatar } from "../ui";

function getBreadcrumbs(pathname, t) {
  const base = { label: t("app.title", "Adaptive Learner"), href: "/map" };
  if (pathname.startsWith("/learn/")) return [base, { label: t("nav.learning") }];
  if (pathname === "/map") return [base, { label: t("nav.conceptMap") }];
  if (pathname === "/dashboard") return [base, { label: t("nav.dashboard", "Dashboard") }];
  if (pathname === "/history") return [base, { label: t("nav.history", "History") }];
  if (pathname === "/leaderboard") return [base, { label: t("nav.leaderboard", "Leaderboard") }];
  if (pathname === "/achievements") return [base, { label: t("nav.achievements", "Achievements") }];
  if (pathname === "/settings") return [base, { label: t("nav.settings") }];
  return [base];
}

export default function StudentTopBar() {
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const { isDark, toggleTheme } = useTheme();
  const { student } = useStudent();

  const isDashboard = location.pathname === "/dashboard";

  /* Sequential back button: each page goes to its logical parent */
  const getBackTarget = () => {
    const p = location.pathname;
    if (p.startsWith("/learn/")) return { label: t("nav.backToMap", "Back to Concept Map"), path: "/map" };
    return { label: t("nav.backToDashboard", "Back to Dashboard"), path: "/dashboard" };
  };

  const back = isDashboard ? null : getBackTarget();

  return (
    <header style={{
      height: "56px", flexShrink: 0, display: "flex", alignItems: "center",
      justifyContent: "space-between", padding: "0 24px",
      background: "#fff", borderBottom: "1px solid #e2e8f0",
    }}>
      {/* Left: Sequential back button or Breadcrumb on dashboard */}
      {isDashboard ? (
        <Breadcrumb items={getBreadcrumbs(location.pathname, t)} />
      ) : (
        <button
          onClick={() => navigate(back.path)}
          style={{
            display: "flex", alignItems: "center", gap: "6px",
            background: "none", border: "none", cursor: "pointer",
            color: "#64748b", fontSize: "13px", fontWeight: 500,
            padding: "6px 10px", borderRadius: "8px",
            transition: "background-color 0.15s",
          }}
          className="hover:bg-slate-50"
        >
          <ArrowLeft size={16} />
          {back.label}
        </button>
      )}

      {/* Right: Controls */}
      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
        <button
          onClick={toggleTheme}
          style={{
            width: 36, height: 36, borderRadius: "10px", border: "none",
            background: "transparent", cursor: "pointer", display: "flex",
            alignItems: "center", justifyContent: "center", color: "#64748b",
          }}
          className="hover:bg-slate-50"
          title={isDark ? t("nav.lightMode") : t("nav.darkMode")}
        >
          {isDark ? <Sun size={18} /> : <Moon size={18} />}
        </button>

        <div style={{ display: "flex", alignItems: "center", gap: "8px", padding: "4px 8px", borderRadius: "10px", cursor: "default" }}>
          <Avatar name={student?.display_name || "S"} size="sm" />
          <span className="hidden lg:inline" style={{ fontSize: "13px", fontWeight: 500, color: "#0f172a", maxWidth: "100px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {student?.display_name}
          </span>
        </div>
      </div>
    </header>
  );
}
