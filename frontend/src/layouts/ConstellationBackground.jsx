import { useReducedMotion, motion } from "framer-motion";

// ── Warm orange/white palette for constellation on orange gradient ─────────
const NODE_COLOR_LARGE  = "rgba(255,255,255,0.55)";  // large bright nodes
const NODE_COLOR_MEDIUM = "rgba(255,255,255,0.40)";  // mid nodes
const NODE_COLOR_SMALL  = "rgba(255,255,255,0.25)";  // small subtle nodes
const EDGE_COLOR        = "rgba(255,255,255,0.15)";

function nodeColor(r) {
  if (r >= 5) return NODE_COLOR_LARGE;
  if (r >= 3) return NODE_COLOR_MEDIUM;
  return NODE_COLOR_SMALL;
}

// ── Node definitions ────────────────────────────────────────────────────────
// cx/cy in 0-100 (percent of SVG viewBox), r in px, opacity 0–1
// drift.x/y = animation range in percentage-points for organic float
const NODES = [
  { id: 0,  cx: 12, cy: 18, r: 2.5, opacity: 0.22, drift: { x:  1.2, y:  0.8 }, duration: 28 },
  { id: 1,  cx: 28, cy: 8,  r: 3.0, opacity: 0.30, drift: { x: -1.0, y:  1.5 }, duration: 33 },
  { id: 2,  cx: 48, cy: 14, r: 5.5, opacity: 0.50, drift: { x:  0.8, y: -1.2 }, duration: 22, bright: true },
  { id: 3,  cx: 70, cy: 10, r: 2.0, opacity: 0.18, drift: { x: -1.5, y:  0.6 }, duration: 38 },
  { id: 4,  cx: 85, cy: 22, r: 3.5, opacity: 0.28, drift: { x:  1.0, y:  1.8 }, duration: 25 },
  { id: 5,  cx: 22, cy: 38, r: 2.0, opacity: 0.20, drift: { x:  0.6, y: -0.9 }, duration: 40 },
  { id: 6,  cx: 38, cy: 32, r: 6.0, opacity: 0.55, drift: { x: -0.9, y:  1.0 }, duration: 20, bright: true },
  { id: 7,  cx: 58, cy: 40, r: 2.8, opacity: 0.25, drift: { x:  1.4, y: -1.4 }, duration: 35 },
  { id: 8,  cx: 78, cy: 35, r: 2.0, opacity: 0.17, drift: { x: -1.2, y:  0.8 }, duration: 30 },
  { id: 9,  cx: 92, cy: 48, r: 3.0, opacity: 0.24, drift: { x:  0.5, y:  1.6 }, duration: 27 },
  { id: 10, cx: 15, cy: 58, r: 2.5, opacity: 0.21, drift: { x:  1.0, y: -0.7 }, duration: 36 },
  { id: 11, cx: 32, cy: 62, r: 2.0, opacity: 0.16, drift: { x: -0.8, y:  1.2 }, duration: 42 },
  { id: 12, cx: 52, cy: 55, r: 5.0, opacity: 0.45, drift: { x:  1.1, y:  0.9 }, duration: 24, bright: true },
  { id: 13, cx: 68, cy: 65, r: 2.5, opacity: 0.22, drift: { x: -1.3, y: -0.6 }, duration: 31 },
  { id: 14, cx: 82, cy: 72, r: 3.0, opacity: 0.26, drift: { x:  0.7, y:  1.3 }, duration: 29 },
  { id: 15, cx: 25, cy: 80, r: 2.0, opacity: 0.19, drift: { x:  1.5, y: -1.0 }, duration: 37 },
  { id: 16, cx: 45, cy: 85, r: 6.5, opacity: 0.52, drift: { x: -1.0, y:  0.7 }, duration: 21, bright: true },
  { id: 17, cx: 72, cy: 88, r: 2.5, opacity: 0.20, drift: { x:  0.9, y: -1.5 }, duration: 34 },
];

// ── Edge definitions (connect nearby nodes) ──────────────────────────────────
const EDGES = [
  { from: 0,  to: 1,  opacity: 0.10 },
  { from: 1,  to: 2,  opacity: 0.14 },
  { from: 2,  to: 4,  opacity: 0.09 },
  { from: 2,  to: 6,  opacity: 0.13 },
  { from: 5,  to: 6,  opacity: 0.11 },
  { from: 6,  to: 7,  opacity: 0.12 },
  { from: 7,  to: 12, opacity: 0.10 },
  { from: 9,  to: 14, opacity: 0.08 },
  { from: 12, to: 13, opacity: 0.12 },
  { from: 16, to: 17, opacity: 0.09 },
];

// Build a lookup so edges can reference node positions
const nodeById = Object.fromEntries(NODES.map((n) => [n.id, n]));

export default function ConstellationBackground() {
  const shouldReduceMotion = useReducedMotion();

  return (
    <svg
      viewBox="0 0 100 100"
      preserveAspectRatio="xMidYMid slice"
      aria-hidden="true"
      className="w-full h-full absolute inset-0 pointer-events-none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        {/* Central ambient glow gradient — white on orange bg */}
        <radialGradient
          id="orb-gradient"
          cx="50%"
          cy="40%"
          r="55%"
          fx="50%"
          fy="40%"
          gradientUnits="objectBoundingBox"
        >
          <stop
            offset="0%"
            stopColor="#FFFFFF"
            stopOpacity="0.12"
          />
          <stop offset="100%" stopColor="transparent" stopOpacity="0" />
        </radialGradient>

        {/* Glow filter for bright nodes */}
        <filter id="node-glow" x="-80%" y="-80%" width="260%" height="260%">
          <feGaussianBlur stdDeviation="1.8" result="blur" />
          <feComposite in="SourceGraphic" in2="blur" operator="over" />
        </filter>
      </defs>

      {/* Background ambient orb */}
      <rect
        x="0"
        y="0"
        width="100"
        height="100"
        fill="url(#orb-gradient)"
      />

      {/* Static edges — lines between nearby nodes */}
      {EDGES.map((edge) => {
        const a = nodeById[edge.from];
        const b = nodeById[edge.to];
        return (
          <line
            key={`${edge.from}-${edge.to}`}
            x1={`${a.cx}%`}
            y1={`${a.cy}%`}
            x2={`${b.cx}%`}
            y2={`${b.cy}%`}
            stroke={EDGE_COLOR}
            strokeOpacity={edge.opacity}
            strokeWidth="0.15"
            strokeLinecap="round"
          />
        );
      })}

      {/* Nodes */}
      {NODES.map((node) => {
        const cxFrom = `${node.cx}%`;
        const cxTo   = `${node.cx + node.drift.x}%`;
        const cyFrom = `${node.cy}%`;
        const cyTo   = `${node.cy + node.drift.y}%`;

        return (
          <g key={node.id}>
            {/* Pulse ring for bright nodes */}
            {node.bright && !shouldReduceMotion && (
              <motion.circle
                cx={cxFrom}
                cy={cyFrom}
                r={node.r}
                fill="none"
                stroke={nodeColor(node.r)}
                strokeOpacity={0}
                strokeWidth="0.4"
                animate={{
                  r:            [node.r, node.r * 3.2],
                  strokeOpacity: [0.35, 0],
                }}
                transition={{
                  duration:    3.2,
                  repeat:      Infinity,
                  ease:        "easeOut",
                  delay:       node.id * 0.4,
                }}
              />
            )}

            {/* Main node circle */}
            {shouldReduceMotion ? (
              <circle
                cx={cxFrom}
                cy={cyFrom}
                r={node.r}
                fill={nodeColor(node.r)}
                fillOpacity={node.opacity}
                filter={node.bright ? "url(#node-glow)" : undefined}
              />
            ) : (
              <motion.circle
                cx={cxFrom}
                cy={cyFrom}
                r={node.r}
                fill={nodeColor(node.r)}
                fillOpacity={node.opacity}
                filter={node.bright ? "url(#node-glow)" : undefined}
                animate={{ cx: [cxFrom, cxTo], cy: [cyFrom, cyTo] }}
                transition={{
                  duration:   node.duration,
                  repeat:     Infinity,
                  repeatType: "reverse",
                  ease:       "easeInOut",
                }}
              />
            )}
          </g>
        );
      })}
    </svg>
  );
}
