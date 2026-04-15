import { AnimatePresence, motion } from 'framer-motion';
import { useTranslation } from 'react-i18next';
import { useAdaptiveStore } from '../../store/adaptiveStore';
import BadgeIcon from './BadgeIcon';

export default function BadgeCelebration() {
  const newBadge = useAdaptiveStore((s) => s.newBadge);
  const { t } = useTranslation();

  return (
    <AnimatePresence>
      {newBadge && (
        <motion.div
          key={newBadge.badge_key}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.25 }}
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 1000,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: 'rgba(0,0,0,0.6)',
          }}
        >
          <motion.div
            initial={{ scale: 0, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0, opacity: 0 }}
            transition={{ type: 'spring', stiffness: 340, damping: 22 }}
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: '1rem',
              padding: '2.5rem 3rem',
              borderRadius: '1.5rem',
              background: 'var(--color-surface, #1e1e2e)',
              boxShadow: '0 0 40px rgba(234,179,8,0.5)',
              minWidth: '280px',
              textAlign: 'center',
            }}
          >
            <BadgeIcon badgeKey={newBadge.badge_key} size={64} earned />

            <div>
              <div
                style={{
                  fontWeight: 800,
                  fontSize: '1.25rem',
                  color: 'var(--color-text, #f1f5f9)',
                  marginBottom: '0.3rem',
                }}
              >
                {t(`badge.${newBadge.badge_key}`)}
              </div>
              <div
                style={{
                  fontSize: '0.9rem',
                  color: 'var(--color-text-muted, #94a3b8)',
                  fontWeight: 500,
                }}
              >
                {t('badge.celebration')}
              </div>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
