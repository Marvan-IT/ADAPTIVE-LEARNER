import { useTranslation } from "react-i18next";
import { User, ArrowRight, UserPlus } from "lucide-react";
import { trackEvent } from "../../utils/analytics";

export default function StudentCard({ student, onContinue, onNewStudent }) {
  const { t } = useTranslation();

  return (
    <div>
      <h2 style={{ fontSize: "1.4rem", fontWeight: 700, color: "var(--color-text)", marginBottom: "1.5rem" }}>
        {t("welcome.welcomeBack")}
      </h2>

      <div style={{
        display: "flex", alignItems: "center", gap: "1rem",
        padding: "1rem", borderRadius: "12px",
        backgroundColor: "var(--color-primary-light)",
        marginBottom: "1.5rem",
      }}>
        <div style={{
          width: "48px", height: "48px", borderRadius: "50%",
          backgroundColor: "var(--color-primary)",
          display: "flex", alignItems: "center", justifyContent: "center",
          color: "#fff",
        }}>
          <User size={24} />
        </div>
        <div>
          <div style={{ fontWeight: 700, fontSize: "1.1rem", color: "var(--color-text)" }}>
            {student.display_name}
          </div>
          {student.interests?.length > 0 && (
            <div style={{ fontSize: "0.85rem", color: "var(--color-text-muted)" }}>
              {t("common.interests")}: {student.interests.map((i) => t("interest." + i, i)).join(", ")}
            </div>
          )}
        </div>
      </div>

      <button
        onClick={() => {
          trackEvent("continue_learning_clicked", {
            student_id: student.id,
            preferred_style: student.preferred_style,
          });
          onContinue();
        }}
        style={{
          display: "flex", alignItems: "center", justifyContent: "center", gap: "0.5rem",
          width: "100%", padding: "0.8rem",
          borderRadius: "12px", border: "none",
          backgroundColor: "var(--color-primary)", color: "#fff",
          fontSize: "1.1rem", fontWeight: 700,
          cursor: "pointer", fontFamily: "inherit",
          transition: "all 0.2s",
        }}
      >
        {t("welcome.continueLearning")} <ArrowRight size={20} />
      </button>

      <button
        onClick={() => {
          trackEvent("new_student_clicked", { student_id: student.id });
          onNewStudent();
        }}
        style={{
          display: "flex", alignItems: "center", justifyContent: "center", gap: "0.5rem",
          width: "100%", padding: "0.6rem", marginTop: "0.75rem",
          borderRadius: "12px", border: "1px solid var(--color-border)",
          backgroundColor: "transparent", color: "var(--color-text-muted)",
          fontSize: "0.9rem", fontWeight: 600,
          cursor: "pointer", fontFamily: "inherit",
        }}
      >
        <UserPlus size={16} /> {t("welcome.newStudent")}
      </button>
    </div>
  );
}
