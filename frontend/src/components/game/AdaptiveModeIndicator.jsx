import { useAdaptiveStore } from '../../store/adaptiveStore';
import { motion, AnimatePresence } from 'framer-motion';

const MODE_CONFIG = {
  NORMAL:     { emoji: '\uD83D\uDCD6', label: 'Normal',        color: '#6b7280', bg: 'rgba(107,114,128,0.12)' },
  FAST:       { emoji: '\u26A1', label: 'Speed Mode',     color: '#f59e0b', bg: 'rgba(245,158,11,0.12)' },
  SLOW:       { emoji: '\uD83E\uDDD8', label: 'Calm Mode',      color: '#6366f1', bg: 'rgba(99,102,241,0.12)' },
  STRUGGLING: { emoji: '\uD83C\uDFAF', label: 'Focus Mode',     color: '#f43f5e', bg: 'rgba(244,63,94,0.12)'  },
  BORED:      { emoji: '\uD83D\uDE80', label: 'Challenge Mode', color: '#22d3ee', bg: 'rgba(34,211,238,0.12)' },
};

export default function AdaptiveModeIndicator({ compact = false }) {
  const mode = useAdaptiveStore((s) => s.mode);
  const cfg = MODE_CONFIG[mode];
  if (!cfg) return null;

  return (
    <motion.div
      layout
      animate={{ backgroundColor: cfg.bg, borderColor: cfg.color, color: cfg.color }}
      transition={{ duration: 0.3 }}
      style={{
        display: 'flex', alignItems: 'center', gap: '0.3rem',
        padding: compact ? '0.15rem 0.5rem' : '0.25rem 0.65rem',
        borderRadius: '9999px',
        border: `1.5px solid ${cfg.color}`,
        fontWeight: 700,
        fontSize: compact ? '0.7rem' : '0.8rem',
        whiteSpace: 'nowrap',
      }}
    >
      <AnimatePresence mode="wait">
        <motion.span
          key={mode}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
        >
          {cfg.emoji} {!compact && cfg.label}
        </motion.span>
      </AnimatePresence>
    </motion.div>
  );
}
