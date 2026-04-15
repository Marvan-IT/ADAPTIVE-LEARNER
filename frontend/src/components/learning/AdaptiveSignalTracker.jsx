import { useState, useEffect, useRef } from 'react';

export default function AdaptiveSignalTracker({
  wrongAttempts = 0,
  hintsUsed = 0,
  idleTriggers = 0,
  learningProfileSummary = null,
  adaptationApplied = null,
  cardIndex = 0,
}) {
  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef(Date.now());

  // Reset timer on card change
  useEffect(() => {
    startRef.current = Date.now();
    setElapsed(0);
  }, [cardIndex]);

  // Tick every second
  useEffect(() => {
    const id = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startRef.current) / 1000));
    }, 1000);
    return () => clearInterval(id);
  }, [cardIndex]);

  const mm = String(Math.floor(elapsed / 60)).padStart(2, '0');
  const ss = String(elapsed % 60).padStart(2, '0');

  return (
    <div
      style={{
        marginTop: "0.75rem",
        borderRadius: "var(--radius-md)",
        border: "1px solid var(--color-border)",
        backgroundColor: "var(--color-surface)",
        padding: "0.5rem 0.75rem",
        fontSize: "0.75rem",
        color: "var(--color-text-muted)",
      }}
    >
      {/* Live signals row */}
      <div style={{ display: "flex", alignItems: "center", gap: "1rem", fontFamily: "monospace" }}>
        <span title="Time on card">⏱ {mm}:{ss}</span>
        <span title="Wrong attempts">✗ {wrongAttempts}</span>
        <span title="Hints used">💡 {hintsUsed}</span>
        <span title="Idle triggers">💤 {idleTriggers}</span>
      </div>

      {/* Post-card profile (appears after card completion) */}
      {learningProfileSummary && (
        <div
          style={{
            marginTop: "0.5rem",
            paddingTop: "0.5rem",
            borderTop: "1px solid var(--color-border)",
          }}
        >
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.375rem", alignItems: "center" }}>
            {learningProfileSummary.speed && (
              <span style={{
                padding: "0.125rem 0.5rem",
                borderRadius: "var(--radius-full)",
                backgroundColor: "color-mix(in srgb, var(--color-primary) 10%, transparent)",
                color: "var(--color-primary)",
                fontSize: "0.625rem",
                fontWeight: 600,
              }}>
                {learningProfileSummary.speed === 'FAST' ? '⚡' : learningProfileSummary.speed === 'SLOW' ? '🐢' : '⏳'} {learningProfileSummary.speed}
              </span>
            )}
            {learningProfileSummary.comprehension && (
              <span style={{
                padding: "0.125rem 0.5rem",
                borderRadius: "var(--radius-full)",
                backgroundColor: "rgba(34,197,94,0.1)",
                color: "var(--color-success)",
                fontSize: "0.625rem",
                fontWeight: 600,
              }}>
                {learningProfileSummary.comprehension === 'STRONG' ? '✓' : learningProfileSummary.comprehension === 'STRUGGLING' ? '⚠️' : '~'} {learningProfileSummary.comprehension}
              </span>
            )}
            {learningProfileSummary.engagement && (
              <span style={{
                padding: "0.125rem 0.5rem",
                borderRadius: "var(--radius-full)",
                backgroundColor: "color-mix(in srgb, var(--color-primary) 10%, transparent)",
                color: "var(--color-primary)",
                fontSize: "0.625rem",
                fontWeight: 600,
              }}>
                {learningProfileSummary.engagement === 'BORED' ? '😴' : learningProfileSummary.engagement === 'OVERWHELMED' ? '😰' : '🎯'} {learningProfileSummary.engagement}
              </span>
            )}
            {adaptationApplied && (
              <span style={{
                padding: "0.125rem 0.5rem",
                borderRadius: "var(--radius-full)",
                backgroundColor: "rgba(139,92,246,0.1)",
                color: "var(--color-primary)",
                fontSize: "0.625rem",
              }}>
                → {adaptationApplied}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
