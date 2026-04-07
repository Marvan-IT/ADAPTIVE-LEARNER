import { useTranslation } from "react-i18next";

export default function MapLegend() {
  const { t } = useTranslation();

  const items = [
    { fill: "rgba(34,197,94,0.12)", border: "rgba(34,197,94,0.6)", labelKey: "map.mastered" },
    { fill: "rgba(99,102,241,0.12)", border: "rgba(99,102,241,0.6)", labelKey: "map.readyToLearn" },
    { fill: "rgba(148,163,184,0.12)", border: "rgba(148,163,184,0.5)", labelKey: "map.locked" },
  ];

  return (
    <div style={{
      position: "absolute", bottom: "1rem", left: "1rem",
      backgroundColor: "var(--color-surface)", borderRadius: "12px",
      border: "1px solid var(--color-border)",
      padding: "0.75rem 1rem",
      display: "flex", gap: "1rem",
      fontSize: "0.85rem", fontWeight: 600,
      boxShadow: "0 2px 8px rgba(0,0,0,0.08)",
      zIndex: 10,
    }}>
      {items.map(({ fill, border, labelKey }) => (
        <div key={labelKey} style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
          <div style={{
            width: "24px", height: "14px", borderRadius: "4px",
            backgroundColor: fill,
            border: `2px solid ${border}`,
          }} />
          <span style={{ color: "var(--color-text)" }}>{t(labelKey)}</span>
        </div>
      ))}
    </div>
  );
}
