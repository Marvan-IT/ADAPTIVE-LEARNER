import { AnimatePresence, motion } from 'framer-motion';
import { useAdaptiveStore } from '../../store/adaptiveStore';

export default function XPBurst() {
  const lastXpGain = useAdaptiveStore((s) => s.lastXpGain);

  return (
    <AnimatePresence>
      {lastXpGain > 0 && (
        <motion.div
          key={lastXpGain + Date.now()}
          initial={{ opacity: 0, y: 0, scale: 0.6 }}
          animate={{ opacity: 1, y: -40, scale: 1.2 }}
          exit={{ opacity: 0, y: -80, scale: 0.8 }}
          transition={{ duration: 1.2, ease: [0.22, 1, 0.36, 1] }}
          style={{
            position: 'fixed',
            bottom: '120px',
            right: '24px',
            zIndex: 9999,
            background: 'linear-gradient(135deg, #f59e0b, #fbbf24)',
            color: '#000',
            fontWeight: 800,
            fontSize: '1.1rem',
            padding: '0.4rem 0.9rem',
            borderRadius: '9999px',
            boxShadow: '0 0 20px rgba(245,158,11,0.7)',
            pointerEvents: 'none',
            userSelect: 'none',
          }}
        >
          +{lastXpGain} XP
        </motion.div>
      )}
    </AnimatePresence>
  );
}
