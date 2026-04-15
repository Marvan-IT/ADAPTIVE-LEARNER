import { useState, useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { formatConceptTitle } from "../../utils/formatConceptTitle";

const BOX_W = 130;
const BOX_H = 38;
const R = 10;
const X_GAP = 140;
const ARROW_GAP = 40;   // space for arrows below nodes
const LABEL_H = 30;     // chapter label height
const PRE_NODE_GAP = 12; // space between label and nodes
const HEADER_H = 80;    // space for book title

const STATUS_STYLES = {
  mastered: { bg: "rgba(34,197,94,0.13)", border: "rgba(34,197,94,0.7)", text: "#16a34a" },
  ready:    { bg: "rgba(59,130,246,0.12)", border: "rgba(59,130,246,0.6)", text: "#2563eb" },
  locked:   { bg: "rgba(148,163,184,0.07)", border: "rgba(148,163,184,0.35)", text: "#94a3b8" },
};

function cleanTitle(title) {
  if (!title) return "";
  return title.replace(/^\d+\.\d+\s*\|\s*/, "").replace(/^\d+\.\d+\s+/, "");
}

export default function ConceptGraph({
  nodes, edges, nodeStatuses, onNodeClick, selectedNode, blinkNodes = [], bookTitle = "", onBackgroundClick,
}) {
  const { t } = useTranslation();
  const [hoveredNode, setHoveredNode] = useState(null);

  /* ── Layout ── */
  const { positions, chapterRows, labelZones, totalW, totalH } = useMemo(() => {
    const chapters = {};
    nodes.forEach((n) => { const ch = n.chapter || "1"; (chapters[ch] ||= []).push(n); });
    const keys = Object.keys(chapters).sort((a, b) => parseFloat(a) - parseFloat(b));

    // Find widest row
    let maxW = 0;
    keys.forEach((ch) => {
      const w = (chapters[ch].length - 1) * X_GAP + BOX_W;
      if (w > maxW) maxW = w;
    });

    const pad = 40;
    const pos = {};
    const rows = [];

    keys.forEach((ch, ci) => {
      const list = [...chapters[ch]].sort((a, b) => parseFloat(a.section) - parseFloat(b.section));
      const rowW = (list.length - 1) * X_GAP + BOX_W;
      const offsetX = (maxW - rowW) / 2;
      // Layout: [ARROW_GAP below prev nodes] → [LABEL_H for chapter label] → [PRE_NODE_GAP] → [nodes]
      const rowBlockH = ARROW_GAP + LABEL_H + PRE_NODE_GAP + BOX_H;
      const labelY = HEADER_H + ci * rowBlockH + ARROW_GAP;
      const nodesY = labelY + LABEL_H + PRE_NODE_GAP;
      const mastered = list.filter((n) => nodeStatuses[n.concept_id] === "mastered").length;

      rows.push({
        chapter: ch, labelY, mastered, total: list.length,
        firstNodeX: pad + offsetX,
      });

      list.forEach((n, ni) => {
        pos[n.concept_id] = { x: pad + offsetX + ni * X_GAP, y: nodesY };
      });
    });

    const labelZones = rows.map((r) => ({ top: r.labelY - 4, bottom: r.labelY + LABEL_H + 4 }));
    const h = rows.length > 0 ? rows[rows.length - 1].labelY + LABEL_H + BOX_H + 80 : 300;
    return { positions: pos, chapterRows: rows, labelZones, totalW: maxW + pad * 2, totalH: h };
  }, [nodes, nodeStatuses]);

  /* Blink */
  const [blinkOn, setBlinkOn] = useState(true);
  useEffect(() => {
    if (!blinkNodes.length) { setBlinkOn(true); return; }
    const iv = setInterval(() => setBlinkOn((v) => !v), 400);
    return () => { clearInterval(iv); setBlinkOn(true); };
  }, [blinkNodes.length > 0 ? blinkNodes.join(",") : ""]);

  const edgeColor = (src, tgt) => {
    const ss = nodeStatuses[src] || "locked", ts = nodeStatuses[tgt] || "locked";
    if (ss === "mastered" && ts === "mastered") return "#86efac";
    if (ss === "mastered" && ts === "ready") return "#93c5fd";
    return "#d1d5db";
  };

  return (
    <div onClick={onBackgroundClick} style={{ width: "100%", height: "100%", overflowY: "auto", overflowX: "auto", background: "var(--color-bg)" }}>
      <div style={{ position: "relative", width: totalW, minHeight: totalH, margin: "0 auto" }}>

        {/* Book title */}
        {bookTitle && (
          <div style={{
            padding: "28px 20px 12px", textAlign: "center",
          }}>
            <div style={{
              display: "inline-flex", flexDirection: "column", alignItems: "center",
              padding: "14px 40px 16px",
              background: "linear-gradient(145deg, #fff9f2, #fff0e0, #fff7ed)",
              borderRadius: "20px",
              border: "1px solid rgba(249,115,22,0.12)",
              boxShadow: "0 2px 12px rgba(249,115,22,0.08), 0 1px 3px rgba(0,0,0,0.04)",
            }}>
              <span style={{
                fontSize: "22px", fontWeight: 800, color: "#1e293b",
                fontFamily: "'Outfit', sans-serif", letterSpacing: "-0.02em",
                lineHeight: 1.3,
              }}>
                {bookTitle}
              </span>
              <div style={{
                width: "40px", height: "3px", borderRadius: "2px",
                background: "linear-gradient(90deg, #f97316, #fb923c)",
                marginTop: "8px",
              }} />
            </div>
          </div>
        )}

        {/* SVG edges */}
        <svg style={{ position: "absolute", top: 0, left: 0, width: "100%", height: "100%", pointerEvents: "none" }}>
          <defs>
            {[["ag", "#d1d5db"], ["agr", "#86efac"], ["abl", "#93c5fd"]].map(([id, c]) => (
              <marker key={id} id={id} markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">
                <polygon points="0 0, 8 3, 0 6" fill={c} />
              </marker>
            ))}
          </defs>
          {edges.map(({ source, target }, i) => {
            const sp = positions[source], tp = positions[target];
            if (!sp || !tp) return null;
            const x1 = sp.x + BOX_W / 2, y1 = sp.y + BOX_H;
            const x2 = tp.x + BOX_W / 2, y2 = tp.y;
            const col = edgeColor(source, target);
            const mk = col === "#86efac" ? "url(#agr)" : col === "#93c5fd" ? "url(#abl)" : "url(#ag)";
            if (Math.abs(sp.y - tp.y) < 10) {
              /* Same-chapter arc — curve BELOW the nodes to avoid the chapter label above */
              const arcY = sp.y + BOX_H + 14;
              return <path key={i} d={`M${x1} ${sp.y + BOX_H} C${x1} ${arcY}, ${x2} ${arcY}, ${x2} ${tp.y + BOX_H}`} fill="none" stroke={col} strokeWidth={1.5} markerEnd={mk} opacity={0.45} />;
            }
            /* Short stubs clipped to never enter any chapter label zone */
            let stubDownY = y1 + 12;
            let stubUpY = y2 - 8;
            for (const z of labelZones) {
              if (stubDownY >= z.top && y1 < z.top) stubDownY = z.top - 1;
              if (stubUpY <= z.bottom && y2 > z.bottom) stubUpY = z.bottom + 1;
            }
            return <g key={i}>
              <line x1={x1} y1={y1} x2={x1} y2={stubDownY} stroke={col} strokeWidth={1.5} opacity={0.4} />
              <line x1={x2} y1={stubUpY} x2={x2} y2={y2} stroke={col} strokeWidth={1.5} opacity={0.4} markerEnd={mk} />
            </g>;
          })}
        </svg>

        {/* Chapter labels — centered with divider lines */}
        {chapterRows.map((cr) => (
          <div key={`ch${cr.chapter}`} style={{
            position: "absolute", top: cr.labelY, left: 0, width: "100%",
            display: "flex", justifyContent: "center", alignItems: "center", gap: "12px",
            opacity: 0.7,
          }}>
            <div style={{ width: "80px", height: "1px", background: "linear-gradient(90deg, transparent, #cbd5e1)" }} />
            <span style={{
              fontSize: "13px", fontWeight: 800, color: "#64748B",
              letterSpacing: "1.2px", textTransform: "uppercase",
              whiteSpace: "nowrap",
            }}>
              {t("map.chapter", "Chapter {{n}}", { n: cr.chapter })}
            </span>
            <span style={{
              fontSize: "11px", fontWeight: 700, color: "#64748b",
              background: "rgba(148,163,184,0.1)", borderRadius: "8px",
              padding: "2px 8px",
            }}>
              {cr.mastered}/{cr.total}
            </span>
            <div style={{ width: "80px", height: "1px", background: "linear-gradient(270deg, transparent, #cbd5e1)" }} />
          </div>
        ))}

        {/* Nodes */}
        {nodes.map((node) => {
          const p = positions[node.concept_id];
          if (!p) return null;
          const status = nodeStatuses[node.concept_id] || "locked";
          const st = STATUS_STYLES[status];
          const title = cleanTitle(node.title || formatConceptTitle(node.concept_id));
          const isSel = selectedNode === node.concept_id;
          const isBlink = blinkNodes.includes(node.concept_id);
          const isHover = hoveredNode === node.concept_id;
          const bc = isSel ? "#2563eb" : isBlink ? "#F97316" : st.border;
          const bw = isSel ? 3 : isBlink ? 3 : isHover ? 2.5 : 1.5;

          return (
            <div key={node.concept_id}
              onClick={(e) => { e.stopPropagation(); onNodeClick(node.concept_id); }}
              onMouseEnter={() => setHoveredNode(node.concept_id)}
              onMouseLeave={() => setHoveredNode(null)}
              style={{
                position: "absolute", left: p.x, top: p.y,
                width: BOX_W, height: BOX_H, borderRadius: R,
                backgroundColor: isBlink && blinkOn ? "#FFF7ED" : st.bg,
                border: `${bw}px solid ${bc}`,
                display: "flex", alignItems: "center", justifyContent: "center",
                padding: "3px 6px", cursor: "pointer",
                opacity: isBlink && !blinkOn ? 0.2 : 1,
                transform: isHover ? "scale(1.03)" : "scale(1)",
                transition: isBlink ? "opacity 0.3s, background-color 0.3s" : "all 0.15s",
                boxShadow: isSel ? `0 0 0 3px ${bc}40, 0 2px 8px rgba(0,0,0,0.1)` : "0 1px 3px rgba(0,0,0,0.04)",
              }}
            >
              <span style={{
                fontSize: "10px", fontWeight: 700, color: st.text,
                textAlign: "center", lineHeight: 1.2, overflow: "hidden",
                display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical",
                fontFamily: "'DM Sans', sans-serif",
              }}>
                {title}
              </span>
            </div>
          );
        })}
      </div>

      {/* Legend */}
      <div style={{
        position: "sticky", bottom: 12, display: "inline-flex", gap: 16,
        padding: "8px 16px", background: "#fff", borderRadius: 12,
        border: "1px solid #e2e8f0", boxShadow: "0 2px 6px rgba(0,0,0,0.05)",
        fontSize: 12, fontWeight: 600, marginLeft: 16, marginBottom: 12,
      }}>
        {[
          { label: t("map.mastered"), s: STATUS_STYLES.mastered },
          { label: t("map.readyToLearn"), s: STATUS_STYLES.ready },
          { label: t("map.locked"), s: STATUS_STYLES.locked },
        ].map(({ label, s }) => (
          <div key={label} style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <div style={{ width: 18, height: 10, borderRadius: 3, backgroundColor: s.bg, border: `2px solid ${s.border}` }} />
            <span style={{ color: "#334155" }}>{label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
