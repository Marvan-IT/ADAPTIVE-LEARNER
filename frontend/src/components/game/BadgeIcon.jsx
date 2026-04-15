import { Star, Trophy, Crown, Flame, Zap, Shield, Timer, Award } from 'lucide-react';

const BADGE_MAP = {
  first_correct:  { Icon: Star,   color: '#eab308' },
  first_mastery:  { Icon: Trophy, color: '#F97316' },
  mastery_5:      { Icon: Crown,  color: '#EA580C' },
  mastery_10:     { Icon: Crown,  color: '#9ca3af' },
  mastery_25:     { Icon: Crown,  color: '#F97316' },
  streak_3:       { Icon: Flame,  color: '#f97316' },
  streak_7:       { Icon: Flame,  color: '#ef4444' },
  streak_14:      { Icon: Flame,  color: '#dc2626' },
  streak_30:      { Icon: Flame,  color: '#991b1b' },
  correct_10:     { Icon: Zap,    color: '#3b82f6' },
  correct_25:     { Icon: Zap,    color: '#1d4ed8' },
  perfect_chunk:  { Icon: Shield, color: 'var(--color-success)' },
  speed_demon:    { Icon: Timer,  color: '#f97316' },
};

const FALLBACK = { Icon: Award, color: '#9ca3af' };

export default function BadgeIcon({ badgeKey, size = 24, earned = true }) {
  const { Icon, color } = BADGE_MAP[badgeKey] ?? FALLBACK;

  return (
    <Icon
      size={size}
      style={{
        color: earned ? color : '#9ca3af',
        opacity: earned ? 1 : 0.4,
        flexShrink: 0,
      }}
    />
  );
}
