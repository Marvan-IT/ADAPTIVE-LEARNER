import { useTranslation } from "react-i18next";
import { cn } from "../ui/lib/utils";
import LevelBadge from "../game/LevelBadge";
import StreakMeter from "../game/StreakMeter";
import StreakMultiplierBadge from "../game/StreakMultiplierBadge";
import AdaptiveModeIndicator from "../game/AdaptiveModeIndicator";
import { ProgressBar } from "../ui";
import { useAdaptiveStore } from "../../store/adaptiveStore";

export default function GamificationHUD({ variant = "sidebar", collapsed = false }) {
  const { t } = useTranslation();
  const xp = useAdaptiveStore((s) => s.xp);
  const level = useAdaptiveStore((s) => s.level);

  if (variant === "compact") {
    return (
      <div className="flex items-center gap-4">
        <LevelBadge size={28} />
        <StreakMeter compact />
        <StreakMultiplierBadge />
        <AdaptiveModeIndicator compact />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className={cn("flex items-center", collapsed ? "justify-center" : "gap-3")}>
        <LevelBadge size={32} />
        {!collapsed && (
          <div className="flex-1 min-w-0">
            <div className="flex justify-between text-xs font-semibold text-[var(--color-text-muted)] mb-1">
              <span>{t("nav.levelShort", { level })}</span>
              <span>{t("nav.xpProgress", { current: xp % 100, max: 100 })}</span>
            </div>
            <ProgressBar value={xp % 100} size="md" color="primary" />
          </div>
        )}
      </div>
      <div className={cn("flex items-center gap-2", collapsed ? "justify-center" : "")}>
        <StreakMeter compact />
        {!collapsed && <StreakMultiplierBadge />}
        {!collapsed && <AdaptiveModeIndicator compact />}
      </div>
    </div>
  );
}
