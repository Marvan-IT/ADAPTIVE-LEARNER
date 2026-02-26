import { Outlet, Navigate, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useStudent } from "../../context/StudentContext";
import StyleSwitcher from "./StyleSwitcher";
import LanguageSelector from "../LanguageSelector";
import { Brain, Map, LogOut } from "lucide-react";

export default function AppShell() {
  const { t } = useTranslation();
  const { student, logout, loading } = useStudent();
  const navigate = useNavigate();

  if (loading) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: "100vh" }}>
        <p style={{ color: "var(--color-text-muted)", fontSize: "1.2rem" }}>{t("common.loading")}</p>
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
          padding: "0.75rem 1.5rem",
          backgroundColor: "var(--color-surface)",
          borderBottom: "2px solid var(--color-border)",
          position: "sticky",
          top: 0,
          zIndex: 50,
        }}
      >
        {/* Left: Logo + Map link */}
        <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
          <div
            onClick={() => navigate("/map")}
            style={{
              display: "flex",
              alignItems: "center",
              gap: "0.5rem",
              cursor: "pointer",
              fontWeight: 800,
              fontSize: "1.3rem",
              color: "var(--color-primary)",
            }}
          >
            <Brain size={28} />
            {t("app.title")}
          </div>
          <button
            onClick={() => navigate("/map")}
            style={{
              display: "flex",
              alignItems: "center",
              gap: "0.4rem",
              padding: "0.4rem 0.8rem",
              background: "var(--color-primary-light)",
              border: "none",
              borderRadius: "8px",
              color: "var(--color-primary)",
              cursor: "pointer",
              fontFamily: "inherit",
              fontSize: "0.9rem",
              fontWeight: 600,
            }}
          >
            <Map size={16} />
            {t("nav.conceptMap")}
          </button>
        </div>

        {/* Center: Student name */}
        <span style={{ fontWeight: 600, color: "var(--color-text)" }}>
          {t("nav.greeting", { name: student.display_name })}
        </span>

        {/* Right: Language + Style + Logout */}
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          <LanguageSelector compact />
          <StyleSwitcher />
          <button
            onClick={() => { logout(); navigate("/"); }}
            style={{
              display: "flex",
              alignItems: "center",
              gap: "0.3rem",
              padding: "0.4rem 0.8rem",
              background: "none",
              border: "1px solid var(--color-border)",
              borderRadius: "8px",
              color: "var(--color-text-muted)",
              cursor: "pointer",
              fontFamily: "inherit",
              fontSize: "0.85rem",
            }}
          >
            <LogOut size={14} />
            {t("nav.switch")}
          </button>
        </div>
      </nav>

      {/* Main Content */}
      <main>
        <Outlet />
      </main>
    </div>
  );
}
