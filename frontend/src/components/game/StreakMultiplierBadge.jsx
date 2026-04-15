import { useTranslation } from 'react-i18next';
import { useAdaptiveStore } from '../../store/adaptiveStore';

export default function StreakMultiplierBadge() {
  const streakMultiplier = useAdaptiveStore((s) => s.streakMultiplier);
  const { t } = useTranslation();

  if (streakMultiplier <= 1.0) return null;

  return (
    <span
      title={t('streak.multiplier')}
      style={{
        display: 'inline-block',
        background: 'linear-gradient(135deg, var(--color-primary-dark), var(--color-primary))',
        color: '#fff',
        fontWeight: 700,
        fontSize: '0.75rem',
        padding: '0.15rem 0.5rem',
        borderRadius: '9999px',
        whiteSpace: 'nowrap',
        lineHeight: 1.4,
        userSelect: 'none',
      }}
    >
      {streakMultiplier}x
    </span>
  );
}
