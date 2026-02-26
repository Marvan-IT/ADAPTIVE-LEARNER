import { useState, useRef, useEffect, useMemo, useCallback } from "react";
import { formatConceptTitle } from "../../utils/formatConceptTitle";

const STATUS_STYLES = {
  mastered: { fill: "#dcfce7", border: "#22c55e", text: "#166534" },
  ready: { fill: "#dbeafe", border: "#3b82f6", text: "#1e40af" },
  locked: { fill: "#f1f5f9", border: "#94a3b8", text: "#64748b" },
};

const BOX_W = 190;
const BOX_H = 44;
const R = 8;
const Y_GAP = 130;
const X_GAP = 220;

export default function ConceptGraph({
  nodes, edges, nodeStatuses, onNodeClick, selectedNode, blinkNodes = [],
}) {
  const svgRef = useRef(null);
  const [tf, setTf] = useState({ x: 0, y: 0, k: 0.75 });
  const [dragging, setDragging] = useState(false);
  const dragOrigin = useRef({ x: 0, y: 0 });
  const [hoveredNode, setHoveredNode] = useState(null);

  /* ── Compute node positions (hierarchical by chapter) ── */
  const positions = useMemo(() => {
    const chapters = {};
    nodes.forEach((n) => {
      const ch = n.chapter || "1";
      if (!chapters[ch]) chapters[ch] = [];
      chapters[ch].push(n);
    });
    const keys = Object.keys(chapters).sort((a, b) => parseFloat(a) - parseFloat(b));
    const pos = {};
    keys.forEach((ch, ci) => {
      const list = chapters[ch];
      const totalW = (list.length - 1) * X_GAP;
      list.forEach((n, ni) => {
        pos[n.concept_id] = {
          x: ni * X_GAP - totalW / 2,
          y: ci * Y_GAP,
        };
      });
    });
    return pos;
  }, [nodes]);

  /* ── Center graph on mount ── */
  useEffect(() => {
    if (!svgRef.current || nodes.length === 0) return;
    const rect = svgRef.current.getBoundingClientRect();
    const xs = Object.values(positions).map((p) => p.x);
    const ys = Object.values(positions).map((p) => p.y);
    if (xs.length === 0) return;
    const minX = Math.min(...xs) - BOX_W;
    const maxX = Math.max(...xs) + BOX_W * 2;
    const minY = Math.min(...ys) - BOX_H;
    const maxY = Math.max(...ys) + BOX_H * 2;
    const gw = maxX - minX;
    const gh = maxY - minY;
    const scale = Math.min(rect.width / gw, rect.height / gh, 1) * 0.8;
    setTf({
      x: rect.width / 2 - (minX + gw / 2) * scale,
      y: rect.height / 2 - (minY + gh / 2) * scale,
      k: scale,
    });
  }, [nodes, positions]);

  /* ── Pan ── */
  const onMouseDown = (e) => {
    if (e.target.closest(".gnode")) return;
    setDragging(true);
    dragOrigin.current = { x: e.clientX - tf.x, y: e.clientY - tf.y };
  };
  const onMouseMove = useCallback(
    (e) => {
      if (!dragging) return;
      setTf((t) => ({
        ...t,
        x: e.clientX - dragOrigin.current.x,
        y: e.clientY - dragOrigin.current.y,
      }));
    },
    [dragging]
  );
  const onMouseUp = () => setDragging(false);

  /* ── Zoom ── */
  const onWheel = useCallback((e) => {
    e.preventDefault();
    const factor = e.deltaY > 0 ? 0.9 : 1.1;
    const r = svgRef.current.getBoundingClientRect();
    const mx = e.clientX - r.left;
    const my = e.clientY - r.top;
    setTf((t) => {
      const nk = Math.min(Math.max(t.k * factor, 0.15), 3);
      const ratio = nk / t.k;
      return { k: nk, x: mx - (mx - t.x) * ratio, y: my - (my - t.y) * ratio };
    });
  }, []);

  /* ── Blink animation ── */
  const [blinkOn, setBlinkOn] = useState(true);
  const blinkKey = blinkNodes.join(",");
  useEffect(() => {
    if (blinkNodes.length === 0) { setBlinkOn(true); return; }
    let count = 0;
    setBlinkOn(false);
    const iv = setInterval(() => {
      count++;
      setBlinkOn((v) => !v);
      if (count >= 6) { clearInterval(iv); setBlinkOn(true); }
    }, 250);
    return () => clearInterval(iv);
  }, [blinkKey]);

  /* ── Edge color helpers ── */
  const edgeColor = (src, tgt) => {
    const ss = nodeStatuses[src] || "locked";
    const ts = nodeStatuses[tgt] || "locked";
    if (ss === "mastered" && ts === "mastered") return "#86efac";
    if (ss === "mastered" && ts === "ready") return "#93c5fd";
    return "#cbd5e1";
  };

  return (
    <svg
      ref={svgRef}
      style={{
        width: "100%", height: "100%",
        backgroundColor: "var(--color-bg)",
        cursor: dragging ? "grabbing" : "grab",
      }}
      onMouseDown={onMouseDown}
      onMouseMove={onMouseMove}
      onMouseUp={onMouseUp}
      onMouseLeave={onMouseUp}
      onWheel={onWheel}
    >
      <defs>
        {/* Arrow markers for each color */}
        {[
          ["arr-gray", "#cbd5e1"],
          ["arr-green", "#86efac"],
          ["arr-blue", "#93c5fd"],
        ].map(([id, color]) => (
          <marker
            key={id} id={id}
            markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto"
          >
            <polygon points="0 0, 10 4, 0 8" fill={color} />
          </marker>
        ))}
      </defs>

      <g transform={`translate(${tf.x},${tf.y}) scale(${tf.k})`}>
        {/* ── Edges ── */}
        {edges.map(({ source, target }, i) => {
          const sp = positions[source];
          const tp = positions[target];
          if (!sp || !tp) return null;

          const x1 = sp.x + BOX_W / 2;
          const y1 = sp.y + BOX_H;
          const x2 = tp.x + BOX_W / 2;
          const y2 = tp.y;

          const col = edgeColor(source, target);
          const marker =
            col === "#86efac" ? "url(#arr-green)" :
            col === "#93c5fd" ? "url(#arr-blue)" : "url(#arr-gray)";

          let d;
          if (Math.abs(sp.y - tp.y) < 10) {
            // Same chapter — arc above
            const arcY = sp.y - 50;
            d = `M ${x1} ${sp.y} C ${x1} ${arcY}, ${x2} ${arcY}, ${x2} ${tp.y}`;
          } else {
            const my = (y1 + y2) / 2;
            d = `M ${x1} ${y1} C ${x1} ${my}, ${x2} ${my}, ${x2} ${y2}`;
          }

          return (
            <path
              key={`e${i}`} d={d}
              fill="none" stroke={col} strokeWidth={2}
              markerEnd={marker}
              opacity={0.7}
            />
          );
        })}

        {/* ── Nodes (boxes) ── */}
        {nodes.map((node) => {
          const p = positions[node.concept_id];
          if (!p) return null;

          const status = nodeStatuses[node.concept_id] || "locked";
          const st = STATUS_STYLES[status];
          const title = node.title || formatConceptTitle(node.concept_id);
          const isSel = selectedNode === node.concept_id;
          const isBlink = blinkNodes.includes(node.concept_id);
          const isHover = hoveredNode === node.concept_id;

          const opacity = isBlink && !blinkOn ? 0.15 : 1;
          const sw = isSel ? 3 : isBlink ? 3 : isHover ? 2.5 : 1.5;
          const bc = isSel ? "#2563eb" : isBlink ? "#f59e0b" : st.border;
          const scale = isHover ? 1.04 : 1;

          return (
            <g
              key={node.concept_id}
              className="gnode"
              onClick={() => onNodeClick(node.concept_id)}
              onMouseEnter={() => setHoveredNode(node.concept_id)}
              onMouseLeave={() => setHoveredNode(null)}
              style={{ cursor: "pointer", opacity, transition: "opacity 0.15s" }}
              transform={`translate(${p.x + BOX_W / 2}, ${p.y + BOX_H / 2}) scale(${scale}) translate(${-(p.x + BOX_W / 2)}, ${-(p.y + BOX_H / 2)})`}
            >
              {/* Shadow */}
              <rect
                x={p.x + 2} y={p.y + 2}
                width={BOX_W} height={BOX_H} rx={R}
                fill="rgba(0,0,0,0.06)"
              />
              {/* Box */}
              <rect
                x={p.x} y={p.y}
                width={BOX_W} height={BOX_H} rx={R}
                fill={st.fill} stroke={bc} strokeWidth={sw}
              />
              {/* Label via foreignObject for proper text handling */}
              <foreignObject
                x={p.x + 6} y={p.y + 2}
                width={BOX_W - 12} height={BOX_H - 4}
                style={{ pointerEvents: "none" }}
              >
                <div
                  xmlns="http://www.w3.org/1999/xhtml"
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    width: "100%",
                    height: "100%",
                    fontFamily: "Nunito, sans-serif",
                    fontSize: "11.5px",
                    fontWeight: 700,
                    color: st.text,
                    textAlign: "center",
                    lineHeight: 1.2,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    wordBreak: "break-word",
                  }}
                >
                  {title}
                </div>
              </foreignObject>
            </g>
          );
        })}
      </g>
    </svg>
  );
}
