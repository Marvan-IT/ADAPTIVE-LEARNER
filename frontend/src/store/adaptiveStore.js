import { create } from 'zustand';

const LEVEL_XP = 100;

function detectMode(signals) {
  if (!signals) return 'NORMAL';
  const { speed, comprehension, engagement, wrong_attempts, avg_time_per_card } = signals;
  if (speed === 'FAST' && comprehension === 'STRONG') return 'FAST';
  if (comprehension === 'STRUGGLING' && (wrong_attempts || 0) >= 3) return 'STRUGGLING';
  if (engagement === 'BORED') return 'BORED';
  if (speed === 'SLOW' || (avg_time_per_card || 0) > 90) return 'SLOW';
  return 'NORMAL';
}

export const useAdaptiveStore = create((set, get) => ({
  mode: 'NORMAL',
  xp: 0,
  level: 1,
  streak: 0,
  streakBest: 0,
  lastXpGain: 0,
  burnoutScore: 0,
  dailyStreak: 0,
  dailyStreakBest: 0,
  streakMultiplier: 1.0,
  badges: [],
  newBadge: null,
  featureFlags: {},

  awardXP: (amount) => {
    set((state) => {
      const newXp = state.xp + amount;
      const newLevel = Math.floor(newXp / LEVEL_XP) + 1;
      return { xp: newXp, level: newLevel, lastXpGain: amount };
    });
    // Auto-clear burst after 1.5s
    setTimeout(() => set({ lastXpGain: 0 }), 1500);
  },

  recordAnswer: (correct) => {
    set((state) => {
      if (correct) {
        const newStreak = state.streak + 1;
        return { streak: newStreak, streakBest: Math.max(state.streakBest, newStreak) };
      } else {
        return { streak: 0, burnoutScore: state.burnoutScore + 1 };
      }
    });
  },

  setMode: (mode) => set({ mode }),

  updateMode: (signals) => {
    const mode = detectMode(signals);
    set({ mode });
  },

  resetLastXpGain: () => set({ lastXpGain: 0 }),

  setDailyStreak: ({ daily_streak, daily_streak_best, multiplier }) =>
    set({
      dailyStreak: daily_streak ?? 0,
      dailyStreakBest: daily_streak_best ?? 0,
      streakMultiplier: multiplier ?? 1.0,
    }),

  addBadge: (badge) => {
    set((state) => ({
      badges: [...state.badges, badge],
      newBadge: badge,
    }));
    setTimeout(() => set({ newBadge: null }), 3500);
  },

  setFeatureFlags: (flags) => set({ featureFlags: flags }),

  init: (saved) => set((s) => ({
    xp: saved.xp ?? s.xp,
    streak: saved.streak ?? s.streak,
    level: saved.xp != null ? Math.floor(saved.xp / LEVEL_XP) + 1 : s.level,
    dailyStreak: saved.daily_streak ?? s.dailyStreak,
    dailyStreakBest: saved.daily_streak_best ?? s.dailyStreakBest,
  })),
}));

export { detectMode };
