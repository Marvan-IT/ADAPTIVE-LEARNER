import { useTranslation } from "react-i18next";
import { BookOpen, MessageCircle, Trophy } from "lucide-react";
import { useSession } from "../../context/SessionContext";

const steps = [
  { id: "CARDS", labelKey: "learning.steps.learning", icon: BookOpen },
  { id: "CHECKING", labelKey: "learning.steps.practice", icon: MessageCircle },
  { id: "COMPLETED", labelKey: "learning.steps.done", icon: Trophy },
];

export default function ProgressBar({ phase }) {
  const { t } = useTranslation();
  const { currentCardIndex, cards, messages } = useSession();

  // Map phase to step index
  const currentIdx = steps.findIndex((s) => s.id === phase);

  return (
    <div style={{
      display: "flex", alignItems: "center", justifyContent: "center",
      gap: "0.75rem", marginBottom: "1.5rem",
    }}>
      {steps.map((step, idx) => {
        const Icon = step.icon;
        const isActive = idx === currentIdx;
        const isDone = idx < currentIdx;

        return (
          <div key={step.id} style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            {idx > 0 && (
              <div style={{
                width: "50px", height: "3px",
                backgroundColor: isDone ? "var(--color-success)" : "var(--color-border)",
                borderRadius: "2px",
              }} />
            )}
            <div style={{
              display: "flex", alignItems: "center", gap: "0.4rem",
              padding: "0.4rem 0.8rem", borderRadius: "20px",
              backgroundColor: isActive ? "var(--color-primary-light)"
                : isDone ? "#dcfce7" : "transparent",
              border: isActive ? "2px solid var(--color-primary)"
                : isDone ? "2px solid var(--color-success)" : "2px solid var(--color-border)",
              color: isActive ? "var(--color-primary)"
                : isDone ? "var(--color-success)" : "var(--color-text-muted)",
              fontWeight: 700, fontSize: "0.85rem",
              transition: "all 0.3s",
            }}>
              <Icon size={16} />
              {t(step.labelKey)}
              {isActive && phase === "CARDS" && cards.length > 0 && (
                <span style={{ fontSize: "0.75rem", opacity: 0.8, marginLeft: "0.2rem" }}>
                  ({currentCardIndex + 1}/{cards.length})
                </span>
              )}
              {isActive && phase === "CHECKING" && messages.length > 0 && (
                <span style={{ fontSize: "0.75rem", opacity: 0.8, marginLeft: "0.2rem" }}>
                  ({Math.floor(messages.filter(m => m.role === "user").length)})
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
