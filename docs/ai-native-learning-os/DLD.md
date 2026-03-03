# Detailed Low-Level Design — AI-Native Learning OS

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-03-01 | Solution Architect | Initial authoring. Full component breakdown, data design, all 10 feature specs including exact CSS/JSX/logic for index.css additions, adaptiveStore.js full code, all 5 game component full code, AppShell/WelcomePage/ConceptMapPage/CardLearningView/AssistantPanel/StudentHistoryPage modification specs, security, observability, error handling, and testing strategy. |

---

**Feature slug:** `ai-native-learning-os`
**Author:** Solution Architect
**Date:** 2026-03-01
**Status:** Approved for implementation

---

## 1. Component Breakdown

### New Files

| Component | File Path | Single Responsibility |
|-----------|-----------|----------------------|
| adaptiveStore | `frontend/src/store/adaptiveStore.js` | Zustand store: game state (XP, level, streak, mode, burnout); all game mechanic mutations |
| GameBackground | `frontend/src/components/game/GameBackground.jsx` | Canvas-based 120-particle animated star field; renders behind page content |
| XPBurst | `frontend/src/components/game/XPBurst.jsx` | Framer Motion "+N XP" gold burst overlay; auto-dismisses after 1.2s |
| StreakMeter | `frontend/src/components/game/StreakMeter.jsx` | Streak count display with fire animation at streak >= 3 |
| LevelBadge | `frontend/src/components/game/LevelBadge.jsx` | Circular SVG badge with level number and XP progress arc |
| AdaptiveModeIndicator | `frontend/src/components/game/AdaptiveModeIndicator.jsx` | Mode pill: label + icon for current adaptive mode |

### Modified Files

| File | Change Type | Scope of Change |
|------|-------------|-----------------|
| `frontend/src/index.css` | Additive extension | New CSS custom properties, keyframes, utility classes — nothing removed |
| `frontend/src/components/layout/AppShell.jsx` | Enhancement | Nav height 58px → 64px; add XP strip, LevelBadge, StreakMeter; add glassmorphism |
| `frontend/src/pages/WelcomePage.jsx` | Enhancement | Add GameBackground, floating island card animations, player profile strip, fog of war |
| `frontend/src/pages/ConceptMapPage.jsx` | Enhancement | Add GameBackground, apply node state CSS classes to Sigma graph container |
| `frontend/src/components/learning/CardLearningView.jsx` | Bug fix + enhancement | Fix AssistantPanel wrapper sticky positioning; add adaptive class, XPBurst, StreakMeter, Framer Motion card entry, mode-specific UI behaviors |
| `frontend/src/components/learning/AssistantPanel.jsx` | Enhancement + bug fix | Fix height calc; add mode-colored header, AnimatePresence message entry, animated thinking dots, adaptive input glow |
| `frontend/src/pages/StudentHistoryPage.jsx` | Enhancement | Add mastery heatmap (7-day grid), achievement badges row, level progression chart |

### Component Interfaces

**adaptiveStore public interface (Zustand `useAdaptiveStore`):**
```js
// Selectors
state.mode          // 'NORMAL' | 'EXCELLING' | 'STRUGGLING' | 'SLOW' | 'BORED'
state.xp            // number  (0–99 within current level)
state.level         // number  (starts at 1)
state.streak        // number  (consecutive correct answers)
state.streakBest    // number  (session best streak)
state.lastXpGain    // number | null  (amount of last XP award; null when no pending burst)
state.burnoutScore  // number  (0–100; internal signal for STRUGGLING detection)

// Actions
actions.awardXP(amount: number): void
actions.recordAnswer(correct: boolean, timeMs: number): void
actions.detectMode(signals: { speed: string, comprehension: string, engagement: string }): void
actions.clearLastXpGain(): void  // called by XPBurst after animation completes
```

---

## 2. Data Design

### Zustand Store State Shape

```js
// frontend/src/store/adaptiveStore.js
const initialState = {
  mode: 'NORMAL',         // current adaptive mode
  xp: 0,                  // XP within current level (0–99)
  level: 1,               // current level number
  streak: 0,              // consecutive correct answer count
  streakBest: 0,          // session high streak
  lastXpGain: null,       // number | null — triggers XPBurst when non-null
  burnoutScore: 0,        // 0–100; increments on wrong answers, decays on correct
};
```

### XP System Rules

```
XP per level = 100
Level up condition: xp >= 100
  → xp = xp - 100
  → level = level + 1

awardXP(amount):
  xp += amount
  lastXpGain = amount     // triggers XPBurst render
  while (xp >= 100):
    level += 1
    xp -= 100

Correct MCQ answer:  awardXP(10)
Correct short answer: awardXP(5)
Wrong answer:        no XP; streak = 0; burnoutScore += 20 (capped at 100)
Correct answer:      burnoutScore = max(0, burnoutScore - 10)
```

### Mode Detection Rules

Mode detection runs inside `recordAnswer` after each answer, and can also be called directly by `detectMode(signals)` when `AdaptiveSignalTracker` reports a profile update.

```
Input signals (from SessionContext / AdaptiveSignalTracker):
  speed:          'FAST' | 'NORMAL' | 'SLOW'
  comprehension:  'STRONG' | 'NORMAL' | 'STRUGGLING'
  engagement:     'ENGAGED' | 'BORED' | 'OVERWHELMED'

Mode resolution order (first match wins):
  1. speed === 'FAST' AND comprehension === 'STRONG'  → EXCELLING
  2. comprehension === 'STRUGGLING' AND burnoutScore >= 60 → STRUGGLING
     (also triggered when 3+ consecutive wrong answers in a card)
  3. speed === 'SLOW' AND avg time per card > 90 seconds   → SLOW
  4. engagement === 'BORED'                                 → BORED
  5. (else)                                                 → NORMAL
```

### CSS Token Definitions (No Data Model — Pure CSS)

Defined in `:root` block in `index.css`. Not derived from backend.

---

## 3. API Design

### No New API Endpoints

This feature is entirely frontend-side. No new backend routes are introduced.

### Zustand Store API (Internal)

Not an HTTP API. Documented here as the contract between components and the store.

```
useAdaptiveStore(selector)
  Returns the selected slice of adaptive state.
  Components should select only what they need to avoid unnecessary re-renders.

Example usage:
  const xp = useAdaptiveStore(s => s.xp);
  const { awardXP, recordAnswer } = useAdaptiveStore(s => s.actions);
```

---

## 4. Detailed Feature Specifications

---

### Feature 1: Game Design System (`index.css`)

All additions are **appended** to the existing `index.css` file after line 235. No existing declarations are modified.

#### 4.1.1 New CSS Custom Properties

Appended to the `:root` block (second `:root` block — same pattern as existing shadow/radius/motion tokens):

```css
/* ── Game design tokens ─────────────────────────── */
:root {
  /* Node state colors */
  --node-locked:    #94a3b8;   /* slate-400 — locked concept nodes */
  --node-available: var(--color-primary);   /* ready-to-learn nodes */
  --node-mastered:  #f59e0b;   /* amber-400 — gold for mastered nodes */
  --node-weak:      var(--color-danger);    /* needs-review nodes */

  /* Glow intensities */
  --glow-xs: 0 0 4px;
  --glow-sm: 0 0 8px;
  --glow-md: 0 0 16px;
  --glow-lg: 0 0 32px;

  /* XP gold palette */
  --xp-gold:  #f59e0b;
  --xp-glow:  rgba(245, 158, 11, 0.6);

  /* Adaptive mode accent colors */
  --adapt-excelling: #f59e0b;   /* gold */
  --adapt-struggling: #ef4444;  /* red — calmer focus ring */
  --adapt-slow:      #3b82f6;  /* blue — calm */
  --adapt-bored:     #a855f7;  /* purple — stimulation */

  /* Spring motion tokens */
  --spring-bounce: cubic-bezier(0.34, 1.56, 0.64, 1);
  --spring-soft:   cubic-bezier(0.25, 0.46, 0.45, 0.94);
}
```

#### 4.1.2 New Keyframe Animations

Appended to the global animations block after the existing `@keyframes slideInUp` at line 144:

```css
@keyframes node-pulse {
  0%, 100% { box-shadow: var(--glow-sm) var(--xp-gold); }
  50%       { box-shadow: var(--glow-lg) var(--xp-gold); }
}

@keyframes node-flicker {
  0%, 90%, 100% { opacity: 1; filter: none; }
  92%           { opacity: 0.6; filter: blur(0.5px); }
  94%           { opacity: 1; filter: none; }
  96%           { opacity: 0.7; filter: blur(1px); }
}

@keyframes xp-burst {
  0%   { opacity: 0; transform: translateY(0) scale(0.5); }
  20%  { opacity: 1; transform: translateY(-12px) scale(1.2); }
  80%  { opacity: 1; transform: translateY(-24px) scale(1); }
  100% { opacity: 0; transform: translateY(-36px) scale(0.9); }
}

@keyframes fog-reveal {
  from { opacity: 1; }
  to   { opacity: 0; }
}

@keyframes streak-fire {
  0%, 100% { transform: scaleY(1) rotate(-2deg); filter: brightness(1); }
  25%       { transform: scaleY(1.1) rotate(2deg); filter: brightness(1.2); }
  50%       { transform: scaleY(0.95) rotate(-1deg); filter: brightness(1.1); }
  75%       { transform: scaleY(1.05) rotate(1deg); filter: brightness(1.3); }
}

@keyframes float {
  0%, 100% { transform: translateY(0px); }
  50%       { transform: translateY(-8px); }
}

@keyframes combo-flash {
  0%   { background-color: var(--xp-gold); transform: scale(1); }
  50%  { background-color: color-mix(in srgb, var(--xp-gold) 60%, white); transform: scale(1.08); }
  100% { background-color: var(--xp-gold); transform: scale(1); }
}
```

#### 4.1.3 New Utility Classes

Appended after the existing `.fade-up` class at line 181:

```css
/* ── Node state classes (applied to concept node wrappers) ── */
.node-mastered {
  animation: node-pulse 2s ease-in-out infinite;
  border-color: var(--node-mastered) !important;
}
.node-locked {
  filter: grayscale(1) blur(1.5px);
  opacity: 0.5;
  pointer-events: none;
}
.node-available {
  border-color: var(--node-available);
  box-shadow: var(--glow-xs) color-mix(in srgb, var(--node-available) 50%, transparent);
}
.node-weak {
  animation: node-flicker 3s ease-in-out infinite;
  border-color: var(--node-weak);
}

/* ── Glass panel ── */
.glass-panel {
  background: color-mix(in srgb, var(--color-surface) 80%, transparent);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1.5px solid color-mix(in srgb, var(--color-border) 60%, transparent);
}

/* ── XP burst overlay ── */
.xp-burst {
  animation: xp-burst 1.2s var(--spring-bounce) forwards;
  pointer-events: none;
  position: absolute;
  font-weight: 800;
  font-size: 1.1rem;
  color: var(--xp-gold);
  text-shadow: var(--glow-sm) var(--xp-glow);
}

/* ── Adaptive mode overlays ── */
.adaptive-excelling {
  border-color: var(--adapt-excelling) !important;
  box-shadow: var(--glow-sm) var(--xp-glow);
}
.adaptive-struggling {
  border-color: var(--adapt-struggling) !important;
  box-shadow: var(--glow-sm) rgba(239, 68, 68, 0.3);
}
.adaptive-slow {
  border-color: var(--adapt-slow) !important;
  font-size: 1.1em;
}
.adaptive-bored {
  border-color: var(--adapt-bored) !important;
  box-shadow: var(--glow-sm) rgba(168, 85, 247, 0.3);
}

/* ── Floating card animation ── */
.float-card {
  animation: float 3s ease-in-out infinite;
}
.float-card:nth-child(2) { animation-delay: 100ms; }
.float-card:nth-child(3) { animation-delay: 200ms; }
```

---

### Feature 2: Zustand Adaptive Store (`frontend/src/store/adaptiveStore.js`)

**Full file specification:**

```js
// frontend/src/store/adaptiveStore.js
import { create } from 'zustand';

const XP_PER_LEVEL = 100;
const BURNOUT_INCREMENT = 20;
const BURNOUT_DECREMENT = 10;
const BURNOUT_THRESHOLD = 60;
const SLOW_THRESHOLD_MS = 90000; // 90 seconds

// Running card-time averages — stored outside state to avoid re-renders
let cardTimeSamples = [];

function detectModeFromSignals({ speed, comprehension, engagement, burnoutScore }) {
  if (speed === 'FAST' && comprehension === 'STRONG') return 'EXCELLING';
  if (comprehension === 'STRUGGLING' && burnoutScore >= BURNOUT_THRESHOLD) return 'STRUGGLING';
  const avgTime = cardTimeSamples.length > 0
    ? cardTimeSamples.reduce((a, b) => a + b, 0) / cardTimeSamples.length
    : 0;
  if (speed === 'SLOW' && avgTime > SLOW_THRESHOLD_MS) return 'SLOW';
  if (engagement === 'BORED') return 'BORED';
  return 'NORMAL';
}

const useAdaptiveStore = create((set, get) => ({
  // ── State ──────────────────────────────────────────────────
  mode: 'NORMAL',
  xp: 0,
  level: 1,
  streak: 0,
  streakBest: 0,
  lastXpGain: null,
  burnoutScore: 0,

  // ── Actions ────────────────────────────────────────────────

  /**
   * awardXP — adds XP and handles level-up.
   * Sets lastXpGain to trigger XPBurst animation.
   * @param {number} amount
   */
  awardXP: (amount) => {
    set((state) => {
      let xp = state.xp + amount;
      let level = state.level;
      while (xp >= XP_PER_LEVEL) {
        xp -= XP_PER_LEVEL;
        level += 1;
      }
      return { xp, level, lastXpGain: amount };
    });
  },

  /**
   * recordAnswer — called after every MCQ or short-answer evaluation.
   * Updates streak, burnoutScore, and recalculates mode.
   * @param {boolean} correct
   * @param {number}  timeMs — time spent on this card in milliseconds
   */
  recordAnswer: (correct, timeMs) => {
    cardTimeSamples.push(timeMs);
    if (cardTimeSamples.length > 10) cardTimeSamples.shift();

    set((state) => {
      const streak = correct ? state.streak + 1 : 0;
      const streakBest = Math.max(state.streakBest, streak);
      const burnoutScore = correct
        ? Math.max(0, state.burnoutScore - BURNOUT_DECREMENT)
        : Math.min(100, state.burnoutScore + BURNOUT_INCREMENT);
      return { streak, streakBest, burnoutScore };
    });
  },

  /**
   * detectMode — called when AdaptiveSignalTracker reports a profile update.
   * @param {{ speed: string, comprehension: string, engagement: string }} signals
   */
  detectMode: (signals) => {
    const { burnoutScore } = get();
    const mode = detectModeFromSignals({ ...signals, burnoutScore });
    set({ mode });
  },

  /**
   * clearLastXpGain — called by XPBurst after animation ends.
   * Prevents burst from re-triggering on store subscription updates.
   */
  clearLastXpGain: () => set({ lastXpGain: null }),
}));

export default useAdaptiveStore;
```

---

### Feature 3: Game Components (`frontend/src/components/game/`)

#### 4.3.1 `GameBackground.jsx`

```jsx
// frontend/src/components/game/GameBackground.jsx
// Canvas star-field: 120 particles, 60fps, colors cycle between
// var(--color-primary) and var(--color-accent) read from CSS at mount time.

import { useEffect, useRef } from 'react';

const PARTICLE_COUNT = 120;

export default function GameBackground() {
  const canvasRef = useRef(null);
  const animRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    // Read theme colors from CSS custom properties
    const style = getComputedStyle(document.documentElement);
    const colorPrimary = style.getPropertyValue('--color-primary').trim() || '#3b82f6';
    const colorAccent  = style.getPropertyValue('--color-accent').trim()  || '#8b5cf6';

    // Resize to fill parent
    const resize = () => {
      canvas.width  = canvas.offsetWidth;
      canvas.height = canvas.offsetHeight;
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);

    // Initialise particles
    const particles = Array.from({ length: PARTICLE_COUNT }, () => ({
      x: Math.random() * canvas.width,
      y: Math.random() * canvas.height,
      r: Math.random() * 2 + 0.5,          // radius 0.5–2.5px
      vx: (Math.random() - 0.5) * 0.3,     // slow drift
      vy: (Math.random() - 0.5) * 0.3,
      alpha: Math.random() * 0.6 + 0.2,    // opacity 0.2–0.8
      color: Math.random() > 0.5 ? colorPrimary : colorAccent,
    }));

    const draw = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      particles.forEach((p) => {
        // Move
        p.x += p.vx;
        p.y += p.vy;
        // Wrap at edges
        if (p.x < 0) p.x = canvas.width;
        if (p.x > canvas.width) p.x = 0;
        if (p.y < 0) p.y = canvas.height;
        if (p.y > canvas.height) p.y = 0;
        // Draw
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fillStyle = p.color;
        ctx.globalAlpha = p.alpha;
        ctx.fill();
      });
      ctx.globalAlpha = 1;
      animRef.current = requestAnimationFrame(draw);
    };
    draw();

    return () => {
      cancelAnimationFrame(animRef.current);
      ro.disconnect();
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      style={{
        position: 'absolute',
        inset: 0,
        width: '100%',
        height: '100%',
        zIndex: 0,
        pointerEvents: 'none',
      }}
    />
  );
}
```

**Parent container requirement:** The page or section that renders `<GameBackground />` must have `position: relative` set. `GameBackground` renders at `z-index: 0`; all page content must be at `z-index: 1` or higher.

#### 4.3.2 `XPBurst.jsx`

```jsx
// frontend/src/components/game/XPBurst.jsx
// Renders a "+N XP" animated label using Framer Motion AnimatePresence.
// Positioned at the bottom of its nearest positioned ancestor.
// Calls clearLastXpGain() on animation complete.

import { AnimatePresence, motion } from 'framer-motion';
import useAdaptiveStore from '../../store/adaptiveStore';

export default function XPBurst() {
  const lastXpGain     = useAdaptiveStore((s) => s.lastXpGain);
  const clearLastXpGain = useAdaptiveStore((s) => s.clearLastXpGain);

  return (
    <AnimatePresence>
      {lastXpGain !== null && (
        <motion.div
          key={`xp-${Date.now()}`}   // unique key forces re-mount on each gain
          aria-live="polite"
          aria-label={`+${lastXpGain} XP`}
          initial={{ opacity: 0, y: 0, scale: 0.5 }}
          animate={{ opacity: 1, y: -28, scale: 1.2 }}
          exit={{ opacity: 0, y: -48, scale: 0.9 }}
          transition={{ duration: 1.2, ease: [0.34, 1.56, 0.64, 1] }}
          onAnimationComplete={clearLastXpGain}
          style={{
            position: 'absolute',
            bottom: '1.5rem',
            left: '50%',
            transform: 'translateX(-50%)',
            pointerEvents: 'none',
            fontWeight: 800,
            fontSize: '1.1rem',
            color: 'var(--xp-gold)',
            textShadow: '0 0 8px var(--xp-glow)',
            zIndex: 10,
            whiteSpace: 'nowrap',
          }}
        >
          +{lastXpGain} XP
        </motion.div>
      )}
    </AnimatePresence>
  );
}
```

#### 4.3.3 `StreakMeter.jsx`

```jsx
// frontend/src/components/game/StreakMeter.jsx
// Displays current streak count.
// When streak >= 3: applies streak-fire keyframe to the flame emoji.

import useAdaptiveStore from '../../store/adaptiveStore';

export default function StreakMeter({ compact = false }) {
  const streak = useAdaptiveStore((s) => s.streak);
  const isOnFire = streak >= 3;

  if (streak === 0 && compact) return null;

  return (
    <div
      aria-label={`Streak: ${streak}`}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '0.3rem',
        fontWeight: 700,
        fontSize: compact ? '0.85rem' : '1rem',
        color: isOnFire ? 'var(--xp-gold)' : 'var(--color-text-muted)',
      }}
    >
      <span
        aria-hidden="true"
        style={{
          display: 'inline-block',
          animation: isOnFire ? 'streak-fire 0.6s ease-in-out infinite' : 'none',
          transformOrigin: 'bottom center',
        }}
      >
        {isOnFire ? '🔥' : '⚡'}
      </span>
      <span>{streak}</span>
    </div>
  );
}
```

#### 4.3.4 `LevelBadge.jsx`

```jsx
// frontend/src/components/game/LevelBadge.jsx
// Circular SVG badge: outer ring is XP progress arc; center shows level number.
// size prop: 'sm' (32px) | 'md' (44px, default)

import useAdaptiveStore from '../../store/adaptiveStore';

const SIZES = { sm: 32, md: 44 };

export default function LevelBadge({ size = 'md' }) {
  const xp    = useAdaptiveStore((s) => s.xp);
  const level = useAdaptiveStore((s) => s.level);

  const dim = SIZES[size] ?? SIZES.md;
  const strokeWidth = size === 'sm' ? 3 : 4;
  const radius      = (dim / 2) - strokeWidth - 1;
  const circumference = 2 * Math.PI * radius;
  const progress = (xp / 100) * circumference;  // xp is 0–99 within level

  return (
    <div
      aria-label={`Level ${level}, ${xp} XP`}
      style={{ position: 'relative', width: dim, height: dim, flexShrink: 0 }}
    >
      <svg width={dim} height={dim} style={{ transform: 'rotate(-90deg)' }}>
        {/* Track */}
        <circle
          cx={dim / 2} cy={dim / 2} r={radius}
          fill="none"
          stroke="var(--color-border)"
          strokeWidth={strokeWidth}
        />
        {/* Progress arc */}
        <circle
          cx={dim / 2} cy={dim / 2} r={radius}
          fill="none"
          stroke="var(--xp-gold)"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={`${progress} ${circumference}`}
          style={{ transition: 'stroke-dasharray 0.4s var(--spring-soft)' }}
        />
      </svg>
      {/* Level number — centered over SVG */}
      <div
        aria-hidden="true"
        style={{
          position: 'absolute',
          inset: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontWeight: 800,
          fontSize: size === 'sm' ? '0.7rem' : '0.85rem',
          color: 'var(--color-text)',
        }}
      >
        {level}
      </div>
    </div>
  );
}
```

#### 4.3.5 `AdaptiveModeIndicator.jsx`

```jsx
// frontend/src/components/game/AdaptiveModeIndicator.jsx
// Pill indicator showing current adaptive mode with icon.
// Hides when mode === 'NORMAL'.

import useAdaptiveStore from '../../store/adaptiveStore';

const MODE_CONFIG = {
  EXCELLING: { icon: '🚀', label: 'Challenge Mode', color: 'var(--adapt-excelling)' },
  STRUGGLING: { icon: '🎯', label: 'Focus Mode',    color: 'var(--adapt-struggling)' },
  SLOW:       { icon: '🧘', label: 'Calm Mode',     color: 'var(--adapt-slow)' },
  BORED:      { icon: '⚡', label: 'Speed Mode',    color: 'var(--adapt-bored)' },
  NORMAL:     { icon: null, label: null,             color: null },
};

export default function AdaptiveModeIndicator() {
  const mode = useAdaptiveStore((s) => s.mode);
  const config = MODE_CONFIG[mode];

  if (mode === 'NORMAL' || !config.label) return null;

  return (
    <div
      role="status"
      aria-label={`Learning mode: ${config.label}`}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '0.3rem',
        padding: '0.2rem 0.6rem',
        borderRadius: 'var(--radius-full)',
        border: `1.5px solid ${config.color}`,
        color: config.color,
        fontSize: '0.75rem',
        fontWeight: 700,
        backgroundColor: `color-mix(in srgb, ${config.color} 12%, transparent)`,
      }}
    >
      <span aria-hidden="true">{config.icon}</span>
      {config.label}
    </div>
  );
}
```

---

### Feature 4: AppShell Game HUD

**File:** `frontend/src/components/layout/AppShell.jsx`

**Precise changes to the nav element:**

1. **Height:** Change inline style `height: "58px"` to `height: "64px"`.

2. **Background + glassmorphism:** Change `backgroundColor: "var(--color-surface)"` to:
   ```js
   background: "color-mix(in srgb, var(--color-surface) 88%, transparent)",
   backdropFilter: "blur(12px)",
   WebkitBackdropFilter: "blur(12px)",
   ```

3. **Bottom border:** Change `borderBottom: "1.5px solid var(--color-border)"` to:
   ```js
   borderBottom: "2px solid color-mix(in srgb, var(--color-primary) 40%, var(--color-border))",
   ```

4. **Center section** — replace the existing Concept Map pill button with:
   ```jsx
   {/* Center: XP strip + LevelBadge */}
   <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
     <LevelBadge size="sm" />
     {/* XP progress bar strip — 120px wide */}
     <div style={{ width: "120px", position: "relative" }}>
       <div style={{
         height: "6px", borderRadius: "var(--radius-full)",
         backgroundColor: "var(--color-border)",
         overflow: "hidden",
       }}>
         <div style={{
           height: "100%",
           width: `${xp}%`,
           backgroundColor: "var(--xp-gold)",
           borderRadius: "var(--radius-full)",
           transition: "width 0.4s var(--spring-soft)",
           boxShadow: "0 0 6px var(--xp-glow)",
         }} />
       </div>
     </div>
     {/* Concept Map pill — moved to right of XP bar */}
     <button onClick={() => navigate("/map")} ... />
   </div>
   ```
   Note: The xp value is obtained via `const xp = useAdaptiveStore(s => s.xp)`.

5. **Right section** — add `<StreakMeter compact />` to the left of the student dropdown button within the right-side div.

6. **Imports to add:**
   ```js
   import useAdaptiveStore from '../../store/adaptiveStore';
   import LevelBadge from '../game/LevelBadge';
   import StreakMeter from '../game/StreakMeter';
   ```

---

### Feature 5: WelcomePage Game World

**File:** `frontend/src/pages/WelcomePage.jsx`

**Changes:**

1. Add `position: "relative"` and `overflow: "hidden"` to the outermost div (line 50, currently has `position: "relative"` but needs `overflow: "hidden"` added).

2. Render `<GameBackground />` as the first child of the outermost div (before all existing content). All existing content needs `position: "relative"` and `zIndex: 1` added to its wrapper to float above the canvas.

3. Apply `.float-card` CSS class to each subject island card rendered by the `StudentCard` / subject selection components. Each card's wrapper div gets `className="float-card"`. The nth-child delay variants in CSS handle the stagger automatically.

4. Add a **player profile strip** directly above the subject cards:
   ```jsx
   {student && (
     <div style={{
       display: "flex", alignItems: "center", gap: "0.75rem",
       marginBottom: "1.5rem",
       padding: "0.75rem 1.25rem",
       borderRadius: "var(--radius-lg)",
       zIndex: 1, position: "relative",
     }}
     className="glass-panel"
     >
       {/* Avatar initial */}
       <div style={{
         width: "42px", height: "42px", borderRadius: "50%",
         backgroundColor: "var(--color-primary)",
         color: "#fff", fontWeight: 800, fontSize: "1.1rem",
         display: "flex", alignItems: "center", justifyContent: "center",
       }}>
         {student.display_name?.[0]?.toUpperCase()}
       </div>
       <div>
         <div style={{ fontWeight: 700, fontSize: "0.9rem" }}>{student.display_name}</div>
         <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
           <LevelBadge size="sm" />
           <StreakMeter compact />
         </div>
       </div>
     </div>
   )}
   ```

5. **Fog of war overlay** on any card with a locked/unavailable state: wrap each such card's content in:
   ```jsx
   <div style={{ position: "relative" }}>
     {card content}
     {isLocked && (
       <div
         onMouseEnter={(e) => { e.currentTarget.style.opacity = "0"; }}
         onMouseLeave={(e) => { e.currentTarget.style.opacity = "1"; }}
         style={{
           position: "absolute", inset: 0,
           borderRadius: "var(--radius-lg)",
           backgroundColor: "color-mix(in srgb, var(--color-bg) 85%, transparent)",
           backdropFilter: "blur(3px)",
           transition: "opacity 0.3s ease",
           display: "flex", alignItems: "center", justifyContent: "center",
           zIndex: 2,
         }}
       >
         <span style={{ fontSize: "1.5rem" }}>🔒</span>
       </div>
     )}
   </div>
   ```

6. **Imports to add:**
   ```js
   import GameBackground from '../components/game/GameBackground';
   import LevelBadge from '../components/game/LevelBadge';
   import StreakMeter from '../components/game/StreakMeter';
   ```

---

### Feature 6: ConceptMapPage Living Neural Map

**File:** `frontend/src/pages/ConceptMapPage.jsx`

**Changes:**

1. The outermost page div (currently has no explicit positioning) must gain `position: "relative"` and `overflow: "hidden"` to contain the canvas.

2. Render `<GameBackground />` as the first child of that div. All existing content gets `position: "relative"` and `zIndex: 1`.

3. The Sigma graph canvas is rendered inside `<ConceptGraph />`. This component renders its own canvas. `GameBackground` sits behind the Sigma layer via z-index. The existing `ConceptGraph.jsx` does not need to change.

4. Apply node state CSS classes to node info panels / legend items based on `nodeStatuses`. The `nodeStatuses` map from `useConceptMap()` provides `{ [conceptId]: 'available' | 'mastered' | 'locked' | 'weak' }`.

5. In the node detail panel (the selected node sidebar), add a CSS class to the node title badge:
   ```jsx
   <div
     className={
       nodeStatuses[selectedNode] === 'mastered' ? 'node-mastered' :
       nodeStatuses[selectedNode] === 'locked'   ? 'node-locked' :
       nodeStatuses[selectedNode] === 'weak'     ? 'node-weak' :
       'node-available'
     }
   >
     {/* existing node title */}
   </div>
   ```

6. **Imports to add:**
   ```js
   import GameBackground from '../components/game/GameBackground';
   ```

---

### Feature 7: AssistantPanel Sticky Fix (CRITICAL BUG)

**Root Cause:** In `CardLearningView.jsx` at lines 616-622, the wrapper div around `AssistantPanel` has no sticky positioning. When the card column scrolls, the panel scrolls with the page and leaves the viewport.

**Additionally:** The parent flex container at the top level of `CardLearningView` uses `alignItems: "flex-start"` already (confirmed by reading the file structure), which is the correct parent-level setting. However the wrapper div itself lacks `alignSelf: "flex-start"` which is required for `position: sticky` to work in a flex context.

**Fix 1 — `CardLearningView.jsx` lines 616-627:**

Current code:
```jsx
<div
  className="transition-all duration-500 overflow-hidden"
  style={{
    width: showAssistant ? "320px" : "0px",
    opacity: showAssistant ? 1 : 0,
    flexShrink: 0,
  }}
>
  <div style={{ width: "320px" }}>
    <AssistantPanel />
  </div>
</div>
```

Replacement code:
```jsx
<div
  className="transition-all duration-500 overflow-hidden"
  style={{
    width: showAssistant ? "320px" : "0px",
    opacity: showAssistant ? 1 : 0,
    flexShrink: 0,
    position: "sticky",
    top: "70px",                   // nav height (64px) + 6px gap
    alignSelf: "flex-start",       // required for sticky in flex context
    maxHeight: "calc(100vh - 70px)",
  }}
>
  <div style={{ width: "320px" }}>
    <AssistantPanel />
  </div>
</div>
```

**Fix 2 — `AssistantPanel.jsx` line 100:**

Current:
```jsx
height: "calc(100vh - 180px)",
```

Replacement:
```jsx
height: "calc(100vh - 86px)",   // 64px nav + 6px gap + 16px panel top padding
```

**Why 86px:** Nav height is 64px (post-HUD update). The panel top edge is 70px from viewport top (matches the `top: 70px` sticky offset). The panel needs 16px bottom clearance. `100vh - 86px = 100vh - (64+6+16)`.

**Expected behavior after fix:**
- `showAssistant === false`: wrapper is 0px wide, opacity 0 — no visual effect.
- `showAssistant === true`: wrapper slides in to 320px width, sticks at 70px from top of viewport, does not scroll away when the card column content below is scrolled.

---

### Feature 8: CardLearningView Adaptive Modules

**File:** `frontend/src/components/learning/CardLearningView.jsx`

**Imports to add:**
```js
import { motion } from 'framer-motion';
import useAdaptiveStore from '../../store/adaptiveStore';
import XPBurst from '../game/XPBurst';
import StreakMeter from '../game/StreakMeter';
```

**8.1 Store integration:**
```js
const mode       = useAdaptiveStore((s) => s.mode);
const awardXP    = useAdaptiveStore((s) => s.awardXP);
const recordAnswer = useAdaptiveStore((s) => s.recordAnswer);
const detectMode = useAdaptiveStore((s) => s.detectMode);
```

**8.2 Card container adaptive class:**
The outermost card container div receives a dynamic `className` based on `mode`:
```jsx
const adaptiveClass =
  mode === 'EXCELLING' ? 'adaptive-excelling' :
  mode === 'STRUGGLING' ? 'adaptive-struggling' :
  mode === 'SLOW'       ? 'adaptive-slow' :
  mode === 'BORED'      ? 'adaptive-bored' : '';
```
Add `className={adaptiveClass}` to the card's outer border div.

**8.3 XP award on correct answer:**
In the MCQ answer handler, after the existing correctness check:
```js
if (isCorrect) {
  const timeMs = performance.now() - cardStartTimeRef.current;
  awardXP(10);                              // MCQ correct
  recordAnswer(true, timeMs);
} else {
  const timeMs = performance.now() - cardStartTimeRef.current;
  recordAnswer(false, timeMs);
}
```
For short-answer (open-ended) correct: `awardXP(5)`.

**8.4 Sync mode with existing AdaptiveSignalTracker signals:**
When `learningProfileSummary` changes (already tracked via `useSession`), call `detectMode`:
```js
useEffect(() => {
  if (!learningProfileSummary) return;
  detectMode({
    speed:          learningProfileSummary.speed        || 'NORMAL',
    comprehension:  learningProfileSummary.comprehension || 'NORMAL',
    engagement:     learningProfileSummary.engagement   || 'ENGAGED',
  });
}, [learningProfileSummary]);
```

**8.5 XPBurst placement:**
Wrap the card container div with `position: "relative"` (it likely already has this for the shake animation). Place `<XPBurst />` directly inside that wrapper:
```jsx
<div style={{ position: "relative", ... }}>
  {/* existing card content */}
  <XPBurst />
</div>
```

**8.6 StreakMeter in card header:**
In the card header row (the flex row containing `DifficultyBadge` and card number):
```jsx
<div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", ... }}>
  <DifficultyBadge difficulty={card.difficulty} />
  <StreakMeter compact />
  <span style={{ ... }}>{currentCardIndex + 1} / {cards.length}</span>
</div>
```

**8.7 Card entry animation:**
Wrap the card's main content div in a Framer Motion `motion.div`:
```jsx
<motion.div
  key={currentCardIndex}                    // re-mounts on card change
  initial={{ opacity: 0, y: 20 }}
  animate={{ opacity: 1, y: 0 }}
  transition={{ duration: 0.35, ease: 'easeOut' }}
>
  {/* existing card content */}
</motion.div>
```

**8.8 EXCELLING mode — combo badge:**
When `mode === 'EXCELLING'` and `streak >= 3`, render a combo badge in the card header:
```jsx
{mode === 'EXCELLING' && streak >= 3 && (
  <span style={{
    padding: "0.15rem 0.5rem",
    borderRadius: "var(--radius-full)",
    backgroundColor: "var(--xp-gold)",
    color: "#fff",
    fontWeight: 800,
    fontSize: "0.7rem",
    animation: "combo-flash 0.8s ease-in-out infinite",
  }}>
    COMBO x{streak}
  </span>
)}
```

**8.9 STRUGGLING mode — auto-show hint after 2nd wrong attempt:**
In the wrong-answer handler, after incrementing `wrongAttemptsRef`:
```js
if (wrongAttemptsRef.current >= 2 && mode === 'STRUGGLING') {
  sendAssistMessage(null, 'hint_suggestion');  // existing assist API
}
```

**8.10 SLOW mode — font size increase:**
The `.adaptive-slow` CSS class already applies `font-size: 1.1em` to the card container. MCQ option buttons receive additional padding in slow mode:
```jsx
style={{
  padding: mode === 'SLOW' ? "0.7rem 1.2rem" : "0.5rem 0.9rem",
  // ... rest of existing button styles
}}
```

---

### Feature 9: AssistantPanel AI Companion

**File:** `frontend/src/components/learning/AssistantPanel.jsx`

**Imports to add:**
```js
import { motion, AnimatePresence } from 'framer-motion';
import useAdaptiveStore from '../../store/adaptiveStore';
```

**9.1 Mode-colored header:**
```js
const mode = useAdaptiveStore((s) => s.mode);

const MODE_HEADER_COLORS = {
  EXCELLING: 'linear-gradient(135deg, var(--adapt-excelling), #d97706)',
  STRUGGLING: 'linear-gradient(135deg, var(--adapt-struggling), #dc2626)',
  SLOW:       'linear-gradient(135deg, var(--adapt-slow), #1d4ed8)',
  BORED:      'linear-gradient(135deg, var(--adapt-bored), #7c3aed)',
  NORMAL:     'linear-gradient(135deg, var(--color-accent), var(--color-primary))',
};
```
Change the header `background` value from the hardcoded gradient to:
```jsx
background: MODE_HEADER_COLORS[mode] ?? MODE_HEADER_COLORS.NORMAL,
transition: "background 0.5s ease",
```

**9.2 Animated thinking dots:**
Replace the existing `<Loader>` loading indicator inside the messages area with:
```jsx
{assistLoading && (
  <div style={{ display: "flex", alignItems: "center", gap: "0.4rem", padding: "0.4rem 0" }}>
    <div style={{ display: "flex", gap: "4px" }}>
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          style={{
            width: "6px", height: "6px",
            borderRadius: "50%",
            backgroundColor: "var(--color-text-muted)",
            display: "inline-block",
            animation: `dots-bounce 1.2s ease-in-out ${i * 0.2}s infinite`,
          }}
        />
      ))}
    </div>
    <span style={{ fontSize: "0.8rem", color: "var(--color-text-muted)" }}>
      {t("assist.thinking")}
    </span>
  </div>
)}
```
Note: `dots-bounce` keyframe is already defined in `index.css` at line 153.

**9.3 AnimatePresence message entry:**
Replace the raw `assistMessages.map(...)` block with:
```jsx
<AnimatePresence initial={false}>
  {assistMessages.map((msg, idx) => (
    <motion.div
      key={idx}
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: 'easeOut' }}
      style={{ display: "flex", justifyContent: msg.role === "user" ? "flex-end" : "flex-start", marginBottom: "0.5rem" }}
    >
      {/* existing bubble div — unchanged */}
    </motion.div>
  ))}
</AnimatePresence>
```

**9.4 Adaptive input focus glow:**
```jsx
const inputBorderFocusColor = {
  EXCELLING:  'var(--adapt-excelling)',
  STRUGGLING: 'var(--adapt-struggling)',
  SLOW:       'var(--adapt-slow)',
  BORED:      'var(--adapt-bored)',
  NORMAL:     'var(--color-primary)',
}[mode] ?? 'var(--color-primary)';
```
In the input's `onFocus` handler:
```js
onFocus={(e) => (e.target.style.borderColor = inputBorderFocusColor)}
```

---

### Feature 10: StudentHistoryPage Enhancements

**File:** `frontend/src/pages/StudentHistoryPage.jsx`

**10.1 Mastery heatmap (7-day grid):**
Derives from the existing `history` data (array of card interaction records with `answered_at` timestamps).

```jsx
function MasteryHeatmap({ history }) {
  // Build day buckets for last 7 days
  const days = Array.from({ length: 7 }, (_, i) => {
    const d = new Date();
    d.setDate(d.getDate() - (6 - i));
    return d.toDateString();
  });

  const counts = {};
  (history?.card_interactions ?? []).forEach((item) => {
    const day = new Date(item.answered_at).toDateString();
    counts[day] = (counts[day] ?? 0) + 1;
  });
  const maxCount = Math.max(...Object.values(counts), 1);

  return (
    <div style={{ display: "flex", gap: "6px", alignItems: "flex-end", marginBottom: "1.5rem" }}>
      {days.map((day) => {
        const count = counts[day] ?? 0;
        const intensity = count / maxCount;          // 0–1
        return (
          <div
            key={day}
            title={`${day}: ${count} cards`}
            style={{
              width: "32px",
              height: `${8 + intensity * 40}px`,   // 8px min, 48px max
              borderRadius: "var(--radius-sm)",
              backgroundColor: `color-mix(in srgb, var(--color-primary) ${Math.round(intensity * 90 + 10)}%, var(--color-border))`,
              transition: "height 0.4s var(--spring-soft)",
            }}
          />
        );
      })}
    </div>
  );
}
```

**10.2 Achievement badges row:**
Achievement badges are derived from Zustand store state (`streakBest`, `level`) and from session history stats. They are computed in-component — no new API call.

```jsx
function AchievementBadges({ history, streakBest, level }) {
  const badges = [];
  if (streakBest >= 5)  badges.push({ icon: '🔥', label: 'Hot Streak' });
  if (streakBest >= 10) badges.push({ icon: '⚡', label: 'Lightning' });
  if (level >= 2)       badges.push({ icon: '⭐', label: 'Level Up' });
  if (level >= 5)       badges.push({ icon: '🏆', label: 'Champion' });
  const totalCards = history?.card_interactions?.length ?? 0;
  if (totalCards >= 20) badges.push({ icon: '📚', label: '20 Cards' });
  if (totalCards >= 50) badges.push({ icon: '🎓', label: '50 Cards' });

  if (badges.length === 0) return null;

  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", marginBottom: "1.5rem" }}>
      {badges.map((b) => (
        <div
          key={b.label}
          title={b.label}
          style={{
            display: "flex", alignItems: "center", gap: "0.3rem",
            padding: "0.3rem 0.75rem",
            borderRadius: "var(--radius-full)",
            border: "2px solid var(--xp-gold)",
            color: "var(--xp-gold)",
            fontWeight: 700,
            fontSize: "0.8rem",
            backgroundColor: "color-mix(in srgb, var(--xp-gold) 10%, transparent)",
          }}
        >
          <span aria-hidden="true">{b.icon}</span>
          {b.label}
        </div>
      ))}
    </div>
  );
}
```

**10.3 Level progression chart:**
Simple inline bar chart — one bar per session, height proportional to mastery score.

```jsx
function LevelProgressionChart({ history }) {
  const sessions = history?.sessions ?? [];
  if (sessions.length === 0) return null;

  return (
    <div>
      <div style={{ fontSize: "0.8rem", fontWeight: 700, color: "var(--color-text-muted)", marginBottom: "0.5rem" }}>
        Session Mastery Progress
      </div>
      <div style={{ display: "flex", alignItems: "flex-end", gap: "6px", height: "60px" }}>
        {sessions.slice(-12).map((s, i) => (   // show last 12 sessions max
          <div
            key={i}
            title={`Session ${i + 1}: ${Math.round((s.mastery_score ?? 0) * 100)}%`}
            style={{
              flex: 1,
              height: `${Math.max(4, (s.mastery_score ?? 0) * 100)}%`,
              borderRadius: "var(--radius-sm)",
              backgroundColor: s.mastery_score >= 0.7
                ? "var(--color-success)"
                : s.mastery_score >= 0.4
                ? "var(--color-primary)"
                : "var(--color-danger)",
              transition: "height 0.4s var(--spring-soft)",
            }}
          />
        ))}
      </div>
    </div>
  );
}
```

**10.4 Integration into StudentHistoryPage:**
These three components are added to the main `StudentHistoryPage` render, above the existing session/concept table:

```jsx
import useAdaptiveStore from '../store/adaptiveStore';

// Inside StudentHistoryPage component:
const streakBest = useAdaptiveStore((s) => s.streakBest);
const level      = useAdaptiveStore((s) => s.level);

// In JSX, above the existing history content:
<MasteryHeatmap history={history} />
<AchievementBadges history={history} streakBest={streakBest} level={level} />
<LevelProgressionChart history={history} />
```

---

## 5. Integration Design

### Zustand ↔ Existing SessionContext
The Zustand store is **not** a replacement for `SessionContext`. They are parallel:
- `SessionContext` owns: cards, current card index, session, assist messages, mastery data
- `adaptiveStore` owns: game mechanics (XP, level, streak, mode, burnout)

The integration point is `CardLearningView.jsx`, which consumes both. When an answer is evaluated (already handled by SessionContext), `CardLearningView` calls `awardXP` and `recordAnswer` on the Zustand store. When `learningProfileSummary` updates from SessionContext, `CardLearningView` calls `detectMode`.

### Zustand ↔ AdaptiveSignalTracker
`AdaptiveSignalTracker` is a display-only component that receives props from `CardLearningView`. The existing `learningProfileSummary` prop (which comes from `useSession()`) is the signal source for `detectMode`. No changes to `AdaptiveSignalTracker.jsx` are required.

### framer-motion Usage Scope
Framer Motion is used in exactly three locations:
1. `XPBurst.jsx` — `AnimatePresence` + `motion.div`
2. `AssistantPanel.jsx` — `AnimatePresence` + `motion.div` for messages
3. `CardLearningView.jsx` — `motion.div` for card entry animation

No other components import framer-motion. This bounds the dependency and keeps tree-shaking effective.

---

## 6. Security Design

### Not Applicable (Frontend-Only Cosmetic Feature)
This feature introduces no new API endpoints, no new authentication flows, no new data storage, and no new user inputs beyond existing text inputs. All existing security measures remain in place.

The Zustand store holds no sensitive data (XP and level numbers are game mechanics only).

**Canvas safety note:** The `GameBackground` canvas reads CSS custom properties from `getComputedStyle`. This is a safe browser API. No user input is used in canvas rendering.

---

## 7. Observability Design

### Logging
No new structured logging is required — this is a frontend cosmetic layer. The existing PostHog analytics client already captures page views and answer events.

### Analytics Events to Consider Adding (Optional)
If the product team wants to track game engagement, these PostHog events can be added:
- `xp_gained` — `{ amount, total_xp, level }` — fired in `awardXP`
- `level_up` — `{ new_level }` — fired when `level` increments
- `streak_milestone` — `{ streak }` — fired at streak 3, 5, 10
- `adaptive_mode_change` — `{ from_mode, to_mode }` — fired in `detectMode`

These are optional and out of scope for the initial implementation.

---

## 8. Error Handling and Resilience

### Canvas Initialization Failure
If `canvas.getContext('2d')` returns `null` (e.g., hardware acceleration disabled), the `GameBackground` component must handle this gracefully:
```js
const ctx = canvas.getContext('2d');
if (!ctx) return;  // silent fail — canvas is purely cosmetic
```

### Zustand Store Isolation
If the Zustand store throws (not expected, but defensive), it will not affect `SessionContext` or any existing learning functionality because the store is completely separate. Components that fail to read from the store should use default values:
```js
const mode = useAdaptiveStore((s) => s.mode) ?? 'NORMAL';
```

### ResizeObserver Availability
`GameBackground` uses `ResizeObserver`. This is supported in all modern browsers. No polyfill is required for the target audience.

### framer-motion Animation Failures
Framer Motion animations are `transform` and `opacity` only. If the animation system fails to initialize, components render at their final `animate` state (visible, in place) — not blank. This is the safe default.

---

## 9. Testing Strategy

### Unit Tests (Zustand Store)
File: `frontend/src/store/adaptiveStore.test.js`

| Test Name | Assertion |
|-----------|-----------|
| `awardXP adds xp correctly` | After `awardXP(10)`, `state.xp === 10`, `state.lastXpGain === 10` |
| `awardXP triggers level up at 100 XP` | After `awardXP(100)`, `state.level === 2`, `state.xp === 0` |
| `recordAnswer correct increments streak` | After `recordAnswer(true, 5000)`, `state.streak === 1` |
| `recordAnswer wrong resets streak` | After streak of 3, `recordAnswer(false, 5000)` → `state.streak === 0` |
| `recordAnswer wrong increments burnoutScore` | `burnoutScore += 20` per wrong answer |
| `detectMode EXCELLING when fast + strong` | `detectMode({speed:'FAST', comprehension:'STRONG', engagement:'ENGAGED'})` → `mode === 'EXCELLING'` |
| `detectMode STRUGGLING when burnout >= 60` | After 3 wrong answers, `detectMode({comprehension:'STRUGGLING',...})` → `mode === 'STRUGGLING'` |
| `detectMode NORMAL as default` | No signals → `mode === 'NORMAL'` |
| `clearLastXpGain sets lastXpGain to null` | After `awardXP(10)`, `clearLastXpGain()` → `lastXpGain === null` |

### Component Tests (React Testing Library)
- `XPBurst` renders "+10 XP" when `lastXpGain === 10`; does not render when `lastXpGain === null`
- `StreakMeter` renders fire emoji when `streak >= 3`; renders lightning emoji when `streak < 3`
- `LevelBadge` renders correct level number and progress arc width
- `AdaptiveModeIndicator` renders nothing when `mode === 'NORMAL'`; renders "Challenge Mode" when `mode === 'EXCELLING'`

### Integration Tests
- `CardLearningView`: submitting a correct MCQ answer increments `adaptiveStore.xp` by 10
- `CardLearningView`: submitting a wrong answer resets `adaptiveStore.streak` to 0
- `AssistantPanel`: panel is `position: sticky` after `showAssistant === true`
- `AppShell`: LevelBadge and StreakMeter are visible in the nav

### Visual Regression
- Run Playwright screenshot comparison at 1280px width for: WelcomePage (default theme), ConceptMapPage (astronaut theme), CardLearningView with AssistantPanel open (gamer theme)
- Confirm no layout overflow from GameBackground canvas

---

## Key Decisions Requiring Stakeholder Input

1. **`AdaptiveModeIndicator` visibility for students:** The specification shows this component in `CardLearningView`. Confirm whether children should see "Focus Mode / Calm Mode" labels, or if this should be admin/debug-only.
2. **XP reset policy:** Currently XP resets on page reload. If stakeholders want session persistence (localStorage), this is a one-line change in `adaptiveStore.js` using Zustand's `persist` middleware — but the decision must be made before implementation to avoid a partial rollout.
3. **`streakBest` display location:** `streakBest` is tracked in the store but not displayed in the current DLD (it only feeds achievement badges). Confirm whether it should appear in the nav or card header.
4. **SessionContext `learningProfileSummary` field names:** The DLD assumes the fields are `{ speed, comprehension, engagement }` matching what `AdaptiveSignalTracker` receives. Verify these field names against the actual `SessionContext` implementation before connecting `detectMode`.
