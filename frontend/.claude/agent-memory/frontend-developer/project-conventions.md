---
name: ADA frontend project conventions
description: Styling rules, component library patterns, and CSS variable usage confirmed for this project
type: project
---

## Styling
- ZERO inline `style={{}}` in components — Tailwind classes only (enforced by CLAUDE.md)
- CSS design tokens are referenced via Tailwind arbitrary values: `bg-[var(--color-primary)]`
- Exception: SVG-specific numeric attributes (strokeDasharray, strokeDashoffset) may use inline style on SVG circle/path elements only — there is no Tailwind equivalent
- `cn()` helper imported from `./lib/utils` (uses `clsx` underneath)

## Component library — `frontend/src/components/ui/`
- Barrel: `index.js` — always add new exports here
- Current components: Avatar, Badge, Button, Card (+CardHeader/CardContent/CardFooter), Input, ProgressBar, ProgressRing, Skeleton (+TextSkeleton/CardSkeleton/TableSkeleton/GraphSkeleton), Toggle, Tooltip, StrengthBar (+passwordStrength named export)
- `skeleton-shimmer` CSS class is defined in `src/index.css` — use it directly (do not recreate shimmer in JS/Tailwind)

## CSS variables (from `src/index.css`)
- Colors: `--color-primary` (#F97316), `--color-primary-dark` (#EA580C), `--color-primary-light`, `--color-info` (#3B82F6), `--color-success`, `--color-warning`, `--color-danger`, `--color-border`, `--color-text`, `--color-text-muted`, `--color-surface`, `--color-bg`
- Radii: `--radius-sm` (6px), `--radius-md` (12px), `--radius-lg` (16px), `--radius-xl` (24px), `--radius-full` (9999px)

## Orange design system (applied 2026-04-13)
- Buttons: pill shape (rounded-full via `--btn-radius`), bg uses `--color-primary-dark`, whileHover scale 1.02, whileTap scale 0.97
- Cards: rounded-2xl (16px), elevated variant uses motion.div with spring hover (y:-3, boxShadow)
- Inputs/Selects: rounded-xl, h-12, border-2 border-slate-200, focus uses `--color-primary`/`--color-primary-light`
- Modals/Toasts: rounded-2xl panels
- Tables: rounded-2xl container with overflow-hidden, orange-tinted row hover (5% primary), 11px uppercase headers
- ProgressBar: md=10px height, spring-animated fill
- Badge info variant uses `--color-info` (not `--color-primary`)
- Toast info variant border uses `--color-info`
- Score bands: `--score-excellent`, `--score-pass`, `--score-borderline`, `--score-fail`
- Motion: `--motion-fast`, `--motion-normal`, `--motion-standard`, `--spring-bounce`, `--spring-soft`

## Framer Motion
- Version 12.34 — import `{ motion, AnimatePresence }` from `"framer-motion"`
- Used for animated fills/transitions in ProgressBar; `motion.div` with `initial/animate/transition` props
- Toggle uses `motion.span` with `layout` prop + spring transition for knob animation (no x/y needed — layout handles it)
- Tooltip uses `AnimatePresence` + `motion.div` for enter/exit; initial motion direction is derived from `position` prop

## Component patterns
- Tooltip: portal-based (`createPortal` to `document.body`), `useLayoutEffect` for position calculation after paint, edge-detection flips to opposite side if viewport overflow detected. Arrow is a pure CSS border-triangle via Tailwind classes.
- Toggle: `role="switch"` + `aria-checked`; knob positioned with flexbox justify (justify-end / justify-start) rather than absolute positioning — avoids layout shifts.
- StrengthBar: score→class mapping arrays (`barClasses`, `textClasses`) at module scope so Tailwind can statically detect the classes. `passwordStrength` is a named export so pages that already compute the score don't need to import the component.

## Build
- Vite 7.3 — `npx vite build` from `frontend/` directory (not `npm run build` via rtk, which fails in this env)
- KaTeX font warnings at build time are pre-existing and benign
