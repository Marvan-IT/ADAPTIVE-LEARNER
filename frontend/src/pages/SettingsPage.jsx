import { useTranslation } from "react-i18next";
import { User, Palette, Shield, Sun, Moon } from "lucide-react";
import { useStudent } from "../context/StudentContext";
import { useAuth } from "../context/AuthContext";
import { useTheme } from "../context/ThemeContext";
import { Avatar, Button, Toggle, Input } from "../components/ui";
import LanguageSelector from "../components/LanguageSelector";
export default function SettingsPage() {
  const { t } = useTranslation();
  const { student, logout } = useStudent();
  const { user } = useAuth();
  const { isDark, toggleTheme } = useTheme();

  return (
    <div className="flex-1 overflow-y-auto p-6">
    <div className="max-w-2xl mx-auto">
      <h1 className="text-3xl font-bold text-[var(--color-text)] mb-8" style={{ fontFamily: "'Outfit', sans-serif" }}>
        {t("nav.settings")}
      </h1>

      {/* Profile */}
      <div className="bg-[var(--color-surface)] rounded-2xl p-6 border border-[var(--color-border)] mb-6">
        <div className="flex items-center gap-2 mb-6">
          <User size={20} className="text-[var(--color-primary)]" />
          <h2 className="text-lg font-bold text-[var(--color-text)]" style={{ fontFamily: "'Outfit', sans-serif" }}>
            {t("settings.profile", "Profile")}
          </h2>
        </div>
        <div className="flex items-center gap-4 mb-6">
          <Avatar name={student?.display_name || t("common.user", "User")} size="lg" />
          <div>
            <p className="text-lg font-semibold text-[var(--color-text)]">{student?.display_name}</p>
            <p className="text-sm text-[var(--color-text-muted)]">{user?.email}</p>
          </div>
        </div>
        <div className="grid gap-4">
          <div>
            <label className="text-sm font-medium text-[var(--color-text)] mb-1.5 block">{t("settings.displayName", "Display Name")}</label>
            <Input value={student?.display_name || ""} disabled />
          </div>
          <div>
            <label className="text-sm font-medium text-[var(--color-text)] mb-1.5 block">{t("settings.email", "Email")}</label>
            <Input value={user?.email || ""} disabled />
          </div>
          <div>
            <label className="text-sm font-medium text-[var(--color-text)] mb-1.5 block">{t("settings.language", "Language")}</label>
            <LanguageSelector compact={false} />
          </div>
        </div>
      </div>

      {/* Appearance */}
      <div className="bg-[var(--color-surface)] rounded-2xl p-6 border border-[var(--color-border)] mb-6">
        <div className="flex items-center gap-2 mb-6">
          <Palette size={20} className="text-[var(--color-primary)]" />
          <h2 className="text-lg font-bold text-[var(--color-text)]" style={{ fontFamily: "'Outfit', sans-serif" }}>
            {t("settings.appearance", "Appearance")}
          </h2>
        </div>

        {/* Dark mode */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            {isDark ? <Moon size={18} className="text-[var(--color-text-muted)]" /> : <Sun size={18} className="text-amber-500" />}
            <span className="text-sm font-medium text-[var(--color-text)]">
              {isDark ? t("nav.darkMode") : t("nav.lightMode")}
            </span>
          </div>
          <Toggle checked={isDark} onChange={toggleTheme} />
        </div>

      </div>

      {/* Account */}
      <div className="bg-[var(--color-surface)] rounded-2xl p-6 border border-[var(--color-border)]">
        <div className="flex items-center gap-2 mb-6">
          <Shield size={20} className="text-[var(--color-primary)]" />
          <h2 className="text-lg font-bold text-[var(--color-text)]" style={{ fontFamily: "'Outfit', sans-serif" }}>
            {t("settings.account", "Account")}
          </h2>
        </div>
        <div className="flex flex-col gap-3">
          <Button variant="secondary" onClick={async () => { await logout(); window.location.href = "/login"; }}>
            {t("auth.logout")}
          </Button>
          <Button variant="danger" disabled>
            {t("settings.deleteAccount", "Delete Account")}
          </Button>
        </div>
      </div>
    </div>
    </div>
  );
}
