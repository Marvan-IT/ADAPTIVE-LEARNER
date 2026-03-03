import { useAdaptiveStore } from '../../store/adaptiveStore';

export default function StreakMeter({ compact = false }) {
  const streak = useAdaptiveStore((s) => s.streak);
  if (streak < 1) return null;

  const onFire = streak >= 3;

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '0.3rem',
        padding: compact ? '0.2rem 0.5rem' : '0.3rem 0.7rem',
        borderRadius: '9999px',
        background: onFire
          ? 'linear-gradient(135deg, #f97316, #ef4444)'
          : 'color-mix(in srgb, var(--color-primary) 15%, transparent)',
        border: `1.5px solid ${onFire ? '#f97316' : 'var(--color-border)'}`,
        animation: onFire ? 'streak-fire 1.5s ease-in-out infinite' : 'none',
        fontWeight: 700,
        fontSize: compact ? '0.75rem' : '0.85rem',
        color: onFire ? '#fff' : 'var(--color-text)',
        whiteSpace: 'nowrap',
      }}
    >
      {onFire ? '\uD83D\uDD25' : '\u2713'} {streak}
    </div>
  );
}
