import { useAdaptiveStore } from '../../store/adaptiveStore';
import { useTranslation } from 'react-i18next';
import { cn } from '../ui/lib/utils';

export default function StreakMeter({ compact = false }) {
  const dailyStreak = useAdaptiveStore((s) => s.dailyStreak);
  const streakMultiplier = useAdaptiveStore((s) => s.streakMultiplier);
  const { t } = useTranslation();

  if (dailyStreak < 1) return null;

  const onFire = dailyStreak >= 3;

  return (
    <div
      className={cn(
        "flex items-center gap-1.5 rounded-full font-bold whitespace-nowrap",
        compact ? "px-2 py-0.5 text-xs" : "px-3 py-1 text-sm",
        onFire
          ? "bg-gradient-to-r from-orange-500 to-red-500 text-white border-[1.5px] border-orange-500 animate-[pulse_1.5s_ease-in-out_infinite]"
          : "bg-[color-mix(in_srgb,var(--color-primary)_15%,transparent)] text-[var(--color-text)] border-[1.5px] border-[var(--color-border)]"
      )}
      title={t('streak.daily', { count: dailyStreak })}
    >
      <span className={cn(onFire && "animate-[pulse_1.5s_ease-in-out_infinite]")}>
        {onFire ? '\uD83D\uDD25' : '\u2713'}
      </span>
      {' '}{dailyStreak}{t('streak.days')}
      {streakMultiplier > 1.0 && (
        <span className="ml-1 text-[0.7rem] opacity-90">
          {streakMultiplier}x
        </span>
      )}
    </div>
  );
}
