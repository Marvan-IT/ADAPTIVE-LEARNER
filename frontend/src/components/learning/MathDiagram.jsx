/**
 * MathDiagram — renders SVG math visuals from [MATH_DIAGRAM:type:params] markers.
 *
 * Supported types:
 *   base10:hundreds=2,tens=1,ones=5        — base-10 block diagram
 *   place_value_chart                       — Ones → Hundred-Trillions table
 *   number_line:start=0,end=20,mark=7      — horizontal number line
 *   fraction_bar:numerator=3,denominator=4 — colored fraction bar
 */

function parseParams(paramStr) {
  if (!paramStr) return {};
  return paramStr.split(",").reduce((acc, pair) => {
    const [k, v] = pair.split("=");
    if (k && v !== undefined) acc[k.trim()] = isNaN(Number(v)) ? v.trim() : Number(v);
    return acc;
  }, {});
}

// ── Base-10 Blocks ─────────────────────────────────────────────────────────────
function Base10Diagram({ params }) {
  const hundreds = Math.min(params.hundreds ?? 0, 9);
  const tens = Math.min(params.tens ?? 0, 9);
  const ones = Math.min(params.ones ?? 0, 9);

  const BLOCK_SIZE = 28;
  const ROD_W = 10;
  const ROD_H = 28;
  const CUBE_SIZE = 9;
  const GAP = 6;
  const LABEL_H = 20;

  // Calculate widths for each group
  const hundredsW = hundreds > 0 ? hundreds * (BLOCK_SIZE + GAP) : 0;
  const tensW = tens > 0 ? tens * (ROD_W + GAP) : 0;
  const onesW = ones > 0 ? ones * (CUBE_SIZE + GAP) : 0;
  const groupGap = 18;

  const totalW =
    (hundreds > 0 ? hundredsW + groupGap : 0) +
    (tens > 0 ? tensW + groupGap : 0) +
    (ones > 0 ? onesW : 0) +
    16;
  const totalH = BLOCK_SIZE + LABEL_H + 24;

  let x = 8;
  const elements = [];

  // Hundreds: blue filled squares
  if (hundreds > 0) {
    for (let i = 0; i < hundreds; i++) {
      elements.push(
        <g key={`h${i}`}>
          <rect
            x={x + i * (BLOCK_SIZE + GAP)}
            y={LABEL_H}
            width={BLOCK_SIZE}
            height={BLOCK_SIZE}
            fill="#3b82f6"
            stroke="#1d4ed8"
            strokeWidth={1}
            rx={2}
          />
          {/* Grid lines inside hundreds block */}
          {[1,2,3].map(row => (
            <line key={`hr${row}`}
              x1={x + i * (BLOCK_SIZE + GAP)}
              y1={LABEL_H + row * 7}
              x2={x + i * (BLOCK_SIZE + GAP) + BLOCK_SIZE}
              y2={LABEL_H + row * 7}
              stroke="#93c5fd" strokeWidth={0.5}
            />
          ))}
          {[1,2,3].map(col => (
            <line key={`hc${col}`}
              x1={x + i * (BLOCK_SIZE + GAP) + col * 7}
              y1={LABEL_H}
              x2={x + i * (BLOCK_SIZE + GAP) + col * 7}
              y2={LABEL_H + BLOCK_SIZE}
              stroke="#93c5fd" strokeWidth={0.5}
            />
          ))}
        </g>
      );
    }
    elements.push(
      <text key="hlabel" x={x + hundredsW / 2 - 4} y={LABEL_H - 5} fontSize={10} fill="#1d4ed8" textAnchor="middle">
        {hundreds}×100
      </text>
    );
    x += hundredsW + groupGap;
  }

  // Tens: orange vertical rods
  if (tens > 0) {
    for (let i = 0; i < tens; i++) {
      const tx = x + i * (ROD_W + GAP);
      elements.push(
        <g key={`t${i}`}>
          <rect x={tx} y={LABEL_H} width={ROD_W} height={ROD_H} fill="#f97316" stroke="#c2410c" strokeWidth={1} rx={2} />
          {[1,2].map(seg => (
            <line key={`ts${seg}`} x1={tx} y1={LABEL_H + seg * 9} x2={tx + ROD_W} y2={LABEL_H + seg * 9} stroke="#fed7aa" strokeWidth={0.5} />
          ))}
        </g>
      );
    }
    elements.push(
      <text key="tlabel" x={x + tensW / 2 - 4} y={LABEL_H - 5} fontSize={10} fill="#c2410c" textAnchor="middle">
        {tens}×10
      </text>
    );
    x += tensW + groupGap;
  }

  // Ones: green small cubes
  if (ones > 0) {
    for (let i = 0; i < ones; i++) {
      elements.push(
        <rect key={`o${i}`}
          x={x + i * (CUBE_SIZE + GAP)}
          y={LABEL_H + (BLOCK_SIZE - CUBE_SIZE) / 2}
          width={CUBE_SIZE} height={CUBE_SIZE}
          fill="#22c55e" stroke="#15803d" strokeWidth={1} rx={1}
        />
      );
    }
    elements.push(
      <text key="olabel" x={x + onesW / 2 - 4} y={LABEL_H - 5} fontSize={10} fill="#15803d" textAnchor="middle">
        {ones}×1
      </text>
    );
  }

  const total = hundreds * 100 + tens * 10 + ones;

  return (
    <div style={{ margin: "1rem 0", padding: "0.75rem", background: "var(--color-surface, #f8fafc)", borderRadius: "8px", border: "1px solid var(--color-border, #e2e8f0)", display: "inline-block" }}>
      <svg width={Math.max(totalW, 80)} height={totalH} style={{ display: "block" }}>
        {elements}
        <text x={8} y={totalH - 4} fontSize={11} fill="var(--color-text-secondary, #64748b)">
          Total = {total}
        </text>
      </svg>
    </div>
  );
}

// ── Place Value Chart ──────────────────────────────────────────────────────────
function PlaceValueChart() {
  const places = [
    "Hundred Trillions", "Ten Trillions", "Trillions",
    "Hundred Billions", "Ten Billions", "Billions",
    "Hundred Millions", "Ten Millions", "Millions",
    "Hundred Thousands", "Ten Thousands", "Thousands",
    "Hundreds", "Tens", "Ones",
  ];
  const CELL_W = 90;
  const CELL_H = 34;
  const cols = 3;
  const rows = Math.ceil(places.length / cols);

  return (
    <div style={{ margin: "1rem 0", overflowX: "auto" }}>
      <table style={{ borderCollapse: "collapse", fontSize: "12px", background: "var(--color-surface, #f8fafc)" }}>
        <thead>
          <tr>
            {["Millions Period", "Thousands Period", "Ones Period"].map((period) => (
              <th key={period} colSpan={3} style={{ background: "#3b82f6", color: "#fff", padding: "6px 8px", border: "1px solid #1d4ed8", textAlign: "center", fontWeight: 700, fontSize: 11 }}>
                {period}
              </th>
            ))}
          </tr>
          <tr>
            {places.slice(6, 15).concat([]).map((_, i) => null)}
            {places.map((place, i) => (
              <th key={place} style={{
                padding: "8px 6px",
                border: "1px solid var(--color-border, #e2e8f0)",
                background: i % 3 === 0 ? "#eff6ff" : i % 3 === 1 ? "#fefce8" : "#f0fdf4",
                color: "var(--color-text, #1e293b)",
                textAlign: "center",
                fontWeight: 600,
                fontSize: 11,
                minWidth: CELL_W,
                whiteSpace: "nowrap",
              }}>
                {place}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr>
            {places.map((place) => (
              <td key={place} style={{
                padding: "10px 6px",
                border: "1px solid var(--color-border, #e2e8f0)",
                textAlign: "center",
                height: CELL_H,
                minWidth: CELL_W,
                color: "var(--color-text-secondary, #64748b)",
                fontSize: 13,
              }}>
                _
              </td>
            ))}
          </tr>
        </tbody>
      </table>
      <div style={{ fontSize: 11, color: "var(--color-text-secondary, #64748b)", marginTop: 6 }}>
        Each place is 10× the value of the place to its right.
      </div>
    </div>
  );
}

// ── Number Line ────────────────────────────────────────────────────────────────
function NumberLine({ params }) {
  const start = params.start ?? 0;
  const end = Math.max(start + 1, params.end ?? start + 10);
  const mark = params.mark ?? null;
  const count = end - start;

  const W = Math.min(Math.max(count * 28, 200), 500);
  const H = 60;
  const MARGIN = 20;
  const lineY = 35;
  const lineW = W - MARGIN * 2;
  const step = lineW / count;

  const ticks = [];
  for (let i = 0; i <= count; i++) {
    const val = start + i;
    const x = MARGIN + i * step;
    const isMarked = mark !== null && val === mark;
    ticks.push(
      <g key={val}>
        <line x1={x} y1={lineY - 8} x2={x} y2={lineY + 8} stroke={isMarked ? "#3b82f6" : "#64748b"} strokeWidth={isMarked ? 2 : 1} />
        {isMarked && <circle cx={x} cy={lineY} r={6} fill="#3b82f6" />}
        <text x={x} y={lineY + 20} textAnchor="middle" fontSize={count > 15 ? 9 : 11} fill={isMarked ? "#1d4ed8" : "#475569"} fontWeight={isMarked ? 700 : 400}>
          {val}
        </text>
      </g>
    );
  }

  return (
    <div style={{ margin: "1rem 0", padding: "0.5rem", background: "var(--color-surface, #f8fafc)", borderRadius: "8px", border: "1px solid var(--color-border, #e2e8f0)", display: "inline-block" }}>
      <svg width={W} height={H}>
        <line x1={MARGIN} y1={lineY} x2={W - MARGIN} y2={lineY} stroke="#475569" strokeWidth={2} />
        {/* Arrowheads */}
        <polygon points={`${W - MARGIN},${lineY} ${W - MARGIN - 8},${lineY - 4} ${W - MARGIN - 8},${lineY + 4}`} fill="#475569" />
        {ticks}
      </svg>
    </div>
  );
}

// ── Fraction Bar ───────────────────────────────────────────────────────────────
function FractionBar({ params }) {
  const num = Math.max(1, params.numerator ?? 1);
  const den = Math.max(num, params.denominator ?? 4);
  const W = 300;
  const H = 40;
  const segW = W / den;

  const segments = [];
  for (let i = 0; i < den; i++) {
    segments.push(
      <g key={i}>
        <rect x={i * segW} y={0} width={segW} height={H}
          fill={i < num ? "#3b82f6" : "var(--color-surface, #f1f5f9)"}
          stroke="#94a3b8" strokeWidth={1}
        />
        {i < num && (
          <text x={i * segW + segW / 2} y={H / 2 + 4} textAnchor="middle" fontSize={12} fill="#fff" fontWeight={600}>
            {i + 1}/{den}
          </text>
        )}
      </g>
    );
  }

  return (
    <div style={{ margin: "1rem 0", display: "inline-block" }}>
      <div style={{ fontSize: 12, color: "var(--color-text-secondary, #64748b)", marginBottom: 4 }}>
        {num}/{den} = {Math.round((num / den) * 100)}%
      </div>
      <svg width={W} height={H} style={{ borderRadius: 4, overflow: "hidden" }}>
        {segments}
      </svg>
    </div>
  );
}

// ── Main Component ─────────────────────────────────────────────────────────────
export default function MathDiagram({ spec }) {
  if (!spec) return null;

  // Parse "type:params" or just "type"
  const colonIdx = spec.indexOf(":");
  const type = colonIdx === -1 ? spec : spec.slice(0, colonIdx);
  const paramStr = colonIdx === -1 ? "" : spec.slice(colonIdx + 1);
  const params = parseParams(paramStr);

  switch (type.trim()) {
    case "base10":
      return <Base10Diagram params={params} />;
    case "place_value_chart":
      return <PlaceValueChart />;
    case "number_line":
      return <NumberLine params={params} />;
    case "fraction_bar":
      return <FractionBar params={params} />;
    default:
      return null;
  }
}
