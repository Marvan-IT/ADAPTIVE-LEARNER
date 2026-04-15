import { useTranslation } from 'react-i18next';
import BadgeIcon from './BadgeIcon';

const ALL_BADGE_KEYS = [
  'first_correct',
  'first_mastery',
  'mastery_5',
  'mastery_10',
  'mastery_25',
  'streak_3',
  'streak_7',
  'streak_14',
  'streak_30',
  'correct_10',
  'correct_25',
  'perfect_chunk',
  'speed_demon',
];

function formatDate(dateStr) {
  if (!dateStr) return '';
  try {
    return new Date(dateStr).toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  } catch {
    return '';
  }
}

export default function BadgeGrid({ earnedBadges = [] }) {
  const { t } = useTranslation();

  const earnedMap = new Map(earnedBadges.map((b) => [b.badge_key, b]));

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))',
        gap: '1rem',
      }}
    >
      {ALL_BADGE_KEYS.map((key) => {
        const earned = earnedMap.get(key);
        const isEarned = Boolean(earned);

        return (
          <div
            key={key}
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '0.5rem',
              padding: '1rem 0.5rem',
              borderRadius: '0.75rem',
              background: isEarned
                ? 'color-mix(in srgb, var(--color-primary, #F97316) 8%, var(--color-surface, #1e1e2e))'
                : 'var(--color-surface, #1e1e2e)',
              border: `1.5px solid ${isEarned ? 'color-mix(in srgb, var(--color-primary, #F97316) 30%, transparent)' : 'var(--color-border, #334155)'}`,
              textAlign: 'center',
              transition: 'border-color 0.2s ease',
            }}
          >
            <BadgeIcon badgeKey={key} size={32} earned={isEarned} />

            <span
              style={{
                fontSize: '0.75rem',
                fontWeight: isEarned ? 700 : 500,
                color: isEarned
                  ? 'var(--color-text, #f1f5f9)'
                  : 'var(--color-text-muted, #94a3b8)',
                lineHeight: 1.3,
              }}
            >
              {t(`badge.${key}`)}
            </span>

            {isEarned && earned.awarded_at ? (
              <span
                style={{
                  fontSize: '0.65rem',
                  color: 'var(--color-text-muted, #94a3b8)',
                }}
              >
                {formatDate(earned.awarded_at)}
              </span>
            ) : (
              !isEarned && (
                <span
                  style={{
                    fontSize: '0.65rem',
                    color: 'var(--color-text-muted, #94a3b8)',
                  }}
                >
                  {t('badge.locked')}
                </span>
              )
            )}
          </div>
        );
      })}
    </div>
  );
}
