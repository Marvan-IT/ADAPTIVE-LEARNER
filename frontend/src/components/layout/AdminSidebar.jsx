import { useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Brain, LayoutDashboard, BookOpen, Users, MessageSquare, BarChart3, Settings, LogOut, AlertCircle } from "lucide-react";
import { useAuth } from "../../context/AuthContext";

function getNavGroups(t) {
  return [
    {
      label: t("admin.nav.overview", "OVERVIEW"),
      items: [
        { to: "/admin", icon: LayoutDashboard, label: t("admin.nav.dashboard", "Dashboard"), bg: "#FFF7ED", color: "#EA580C", end: true },
      ],
    },
    {
      label: t("admin.nav.content", "CONTENT"),
      items: [
        { to: "/admin", icon: BookOpen, label: t("admin.nav.subjects", "Subjects"), bg: "#DBEAFE", color: "#2563EB", end: true },
      ],
    },
    {
      label: t("admin.nav.users", "USERS"),
      items: [
        { to: "/admin/students", icon: Users, label: t("admin.nav.students", "Students"), bg: "#DCFCE7", color: "#16A34A" },
        { to: "/admin/sessions", icon: MessageSquare, label: t("admin.nav.sessions", "Sessions"), bg: "#CFFAFE", color: "#0891B2" },
      ],
    },
    {
      label: t("admin.nav.insights", "INSIGHTS"),
      items: [
        { to: "/admin/analytics", icon: BarChart3, label: t("admin.nav.analytics", "Analytics"), bg: "#F3E8FF", color: "#9333EA" },
      ],
    },
    {
      label: t("admin.nav.system", "SYSTEM"),
      items: [
        { to: "/admin/settings", icon: Settings, label: t("admin.nav.settings", "Settings"), bg: "#F1F5F9", color: "#475569" },
      ],
    },
  ];
}

export default function AdminSidebar() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { logout } = useAuth();
  const [showLogoutConfirm, setShowLogoutConfirm] = useState(false);
  const NAV_GROUPS = getNavGroups(t);

  return (
    <>
    {/* Logout confirmation modal */}
    {showLogoutConfirm && (
      <div style={{ position: "fixed", inset: 0, zIndex: 9999, display: "flex", alignItems: "center", justifyContent: "center", backgroundColor: "rgba(0,0,0,0.5)" }} onClick={() => setShowLogoutConfirm(false)}>
        <div style={{ backgroundColor: "#FFFFFF", borderRadius: "16px", padding: "24px", maxWidth: "380px", width: "90%", boxShadow: "0 8px 32px rgba(0,0,0,0.15)", border: "1px solid #E2E8F0" }} onClick={(e) => e.stopPropagation()}>
          <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "12px" }}>
            <AlertCircle size={22} color="#F59E0B" />
            <h3 style={{ margin: 0, fontSize: "16px", fontWeight: 700, color: "#0F172A" }}>{t("confirm.logoutTitle", "Logout?")}</h3>
          </div>
          <p style={{ margin: "0 0 20px", fontSize: "14px", color: "#64748B", lineHeight: 1.5 }}>
            {t("confirm.logoutMessage", "Are you sure you want to logout?")}
          </p>
          <div style={{ display: "flex", gap: "10px", justifyContent: "flex-end" }}>
            <button onClick={() => setShowLogoutConfirm(false)} style={{ padding: "8px 16px", borderRadius: "8px", border: "1px solid #E2E8F0", backgroundColor: "transparent", color: "#64748B", fontSize: "14px", fontWeight: 600, cursor: "pointer" }}>
              {t("confirm.cancel", "Cancel")}
            </button>
            <button onClick={async () => { await logout(); navigate("/login"); }} style={{ padding: "8px 16px", borderRadius: "8px", border: "none", backgroundColor: "#EF4444", color: "#FFFFFF", fontSize: "14px", fontWeight: 600, cursor: "pointer" }}>
              {t("nav.logout", "Logout")}
            </button>
          </div>
        </div>
      </div>
    )}
    <aside style={{ width: "260px", height: "100vh", display: "flex", flexDirection: "column", backgroundColor: "#FFFFFF", borderRight: "1px solid #E2E8F0", flexShrink: 0, overflowY: "auto" }}>
      {/* Logo */}
      <div style={{ display: "flex", alignItems: "center", gap: "10px", padding: "20px 20px 16px" }}>
        <div style={{ width: "36px", height: "36px", borderRadius: "50%", background: "linear-gradient(135deg, #FB923C, #EA580C)", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
          <Brain size={18} color="#FFFFFF" />
        </div>
        <span style={{ fontSize: "16px", fontWeight: 800, color: "#0F172A", fontFamily: "'Outfit', sans-serif" }}>
          AL
        </span>
        <span style={{ fontSize: "11px", fontWeight: 600, color: "#EA580C", backgroundColor: "#FFF7ED", padding: "2px 8px", borderRadius: "9999px", flexShrink: 0 }}>
          {t("admin.nav.adminBadge", "Admin")}
        </span>
      </div>

      {/* Nav groups */}
      <nav style={{ flex: 1, padding: "0 12px" }}>
        {NAV_GROUPS.map((group) => (
          <div key={group.label}>
            <div style={{ fontSize: "11px", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", color: "#94A3B8", padding: "16px 12px 6px" }}>
              {group.label}
            </div>
            {group.items.map((item) => {
              const Icon = item.icon;
              return (
                <NavLink
                  key={item.to + item.label}
                  to={item.to}
                  end={item.end}
                  style={({ isActive }) => ({
                    display: "flex",
                    alignItems: "center",
                    gap: "12px",
                    padding: "10px 12px",
                    borderRadius: "12px",
                    fontSize: "14px",
                    fontWeight: isActive ? 600 : 500,
                    color: isActive ? "#EA580C" : "#64748B",
                    backgroundColor: isActive ? "#FFF7ED" : "transparent",
                    borderLeft: isActive ? "3px solid #EA580C" : "3px solid transparent",
                    textDecoration: "none",
                    transition: "background-color 0.15s",
                    marginBottom: "2px",
                  })}
                >
                  <div style={{ width: "32px", height: "32px", borderRadius: "50%", backgroundColor: item.bg, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                    <Icon size={16} color={item.color} />
                  </div>
                  <span>{item.label}</span>
                </NavLink>
              );
            })}
          </div>
        ))}
      </nav>

      {/* Logout */}
      <div style={{ padding: "12px 12px 16px", borderTop: "1px solid #E2E8F0" }}>
        <button
          onClick={() => setShowLogoutConfirm(true)}
          style={{ display: "flex", alignItems: "center", gap: "12px", padding: "10px 12px", borderRadius: "12px", fontSize: "14px", fontWeight: 500, color: "#EF4444", backgroundColor: "transparent", border: "none", cursor: "pointer", width: "100%", textAlign: "left" }}
        >
          <LogOut size={16} />
          <span>{t("nav.logout", "Logout")}</span>
        </button>
      </div>
    </aside>
    </>
  );
}
