import { useTheme } from "../../context/ThemeContext";
import { useTranslation } from "react-i18next";
import { BookOpen, Skull, Rocket, Gamepad2 } from "lucide-react";

const styles = [
  { id: "default", icon: BookOpen, labelKey: "style.default" },
  { id: "pirate", icon: Skull, labelKey: "style.pirate" },
  { id: "astronaut", icon: Rocket, labelKey: "style.astronaut" },
  { id: "gamer", icon: Gamepad2, labelKey: "style.gamer" },
];

export default function StyleSwitcher() {
  const { style, setStyle } = useTheme();
  const { t } = useTranslation();

  return (
    <div style={{ display: "flex", gap: "0.3rem" }}>
      {styles.map(({ id, icon: Icon, labelKey }) => (
        <button
          key={id}
          onClick={() => setStyle(id)}
          title={t(labelKey)}
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            width: "36px",
            height: "36px",
            borderRadius: "8px",
            border: style === id ? "2px solid var(--color-primary)" : "1px solid var(--color-border)",
            background: style === id ? "var(--color-primary-light)" : "transparent",
            color: style === id ? "var(--color-primary)" : "var(--color-text-muted)",
            cursor: "pointer",
            transition: "all 0.2s",
          }}
        >
          <Icon size={18} />
        </button>
      ))}
    </div>
  );
}
