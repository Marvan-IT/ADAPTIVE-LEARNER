import { useAdaptiveStore } from '../../store/adaptiveStore';

const LEVEL_XP = 100;
const R = 16;
const CIRC = 2 * Math.PI * R;

export default function LevelBadge({ size = 36 }) {
  const xp = useAdaptiveStore((s) => s.xp);
  const level = useAdaptiveStore((s) => s.level);
  const progress = (xp % LEVEL_XP) / LEVEL_XP;
  const dash = progress * CIRC;
  const isGold = level >= 5;

  return (
    <div style={{ position: 'relative', width: size, height: size, flexShrink: 0 }}>
      <svg width={size} height={size} viewBox={`0 0 ${size + 4} ${size + 4}`}>
        <circle
          cx={(size + 4) / 2} cy={(size + 4) / 2} r={R}
          fill="none" stroke="var(--color-border)" strokeWidth="2.5"
        />
        <circle
          cx={(size + 4) / 2} cy={(size + 4) / 2} r={R}
          fill="none"
          stroke={isGold ? '#f59e0b' : 'var(--color-primary)'}
          strokeWidth="2.5"
          strokeDasharray={`${dash} ${CIRC}`}
          strokeLinecap="round"
          transform={`rotate(-90 ${(size + 4) / 2} ${(size + 4) / 2})`}
          style={{ transition: 'stroke-dasharray 0.4s ease' }}
        />
      </svg>
      <div style={{
        position: 'absolute', inset: 0,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontWeight: 800, fontSize: size < 32 ? '0.65rem' : '0.75rem',
        color: isGold ? '#f59e0b' : 'var(--color-primary)',
      }}>
        {level}
      </div>
    </div>
  );
}
