import { cn } from "./lib/utils";

const barClasses = [
  "",
  "bg-[var(--color-danger)]",
  "bg-[var(--color-warning)]",
  "bg-[var(--color-info)]",
  "bg-[var(--color-success)]",
];

const textClasses = [
  "",
  "text-[var(--color-danger)]",
  "text-[var(--color-warning)]",
  "text-[var(--color-info)]",
  "text-[var(--color-success)]",
];

/**
 * Returns { score: 0-4, label: string, color: string (CSS var reference) }
 */
export function passwordStrength(pw) {
  if (!pw) return { score: 0, label: "", color: "transparent" };
  let score = 0;
  if (pw.length >= 8) score++;
  if (/[A-Z]/.test(pw)) score++;
  if (/[0-9]/.test(pw)) score++;
  if (/[^A-Za-z0-9]/.test(pw)) score++;
  const colors = [
    "transparent",
    "var(--color-danger)",
    "var(--color-warning)",
    "var(--color-info)",
    "var(--color-success)",
  ];
  const labels = ["", "Weak", "Fair", "Good", "Strong"];
  return { score, label: labels[score], color: colors[score] };
}

/**
 * @param {string} props.password
 * @param {string} [props.className]
 */
export default function StrengthBar({ password, className }) {
  const { score, label } = passwordStrength(password);

  if (!password) return null;

  return (
    <div className={cn("mt-2", className)}>
      <div className="flex gap-1 mb-1">
        {[1, 2, 3, 4].map((i) => (
          <div
            key={i}
            className={cn(
              "flex-1 h-[3px] rounded-sm transition-colors",
              i <= score ? barClasses[score] : "bg-[var(--color-border)]"
            )}
          />
        ))}
      </div>
      {label && (
        <span className={cn("text-xs font-medium", textClasses[score])}>
          {label}
        </span>
      )}
    </div>
  );
}
