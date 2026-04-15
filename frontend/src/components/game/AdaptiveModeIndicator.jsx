import { useAdaptiveStore } from '../../store/adaptiveStore';
import { useTranslation } from 'react-i18next';
import { motion, AnimatePresence } from 'framer-motion';

const MODE_CONFIG = {
  NORMAL:     { emoji: '\uD83D\uDCD6', color: '#6b7280', bg: 'rgba(107,114,128,0.12)' },
  FAST:       { emoji: '\u26A1',       color: '#F97316', bg: 'rgba(249,115,22,0.12)' },
  SLOW:       { emoji: '\uD83E\uDDD8', color: 'var(--color-primary)', bg: 'color-mix(in srgb, var(--color-primary) 12%, transparent)' },
  STRUGGLING: { emoji: '\uD83C\uDFAF', color: '#f43f5e', bg: 'rgba(244,63,94,0.12)'  },
  BORED:      { emoji: '\uD83D\uDE80', color: '#22d3ee', bg: 'rgba(34,211,238,0.12)' },
};

export default function AdaptiveModeIndicator({ compact = false }) {
  const { t } = useTranslation();
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
          {cfg.emoji} {!compact && t(`learning.mode.${mode}`)}
        </motion.span>
      </AnimatePresence>
    </motion.div>
  );
}
