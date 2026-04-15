import { cn } from "./lib/utils";

/**
 * Centered empty state placeholder.
 * @param {Object} props
 * @param {import('react').ReactNode} [props.icon] - Lucide icon element
 * @param {string} props.title - Heading text
 * @param {string} [props.description] - Supporting text
 * @param {import('react').ReactNode} [props.action] - Action button or link
 * @param {string} [props.className]
 */
export default function EmptyState({ icon, title, description, action, className }) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center py-16 px-6 text-center",
        className
      )}
    >
      {icon && (
        <div className="mb-4 text-[var(--color-text-muted)] opacity-40">
          {icon}
        </div>
      )}
      <h3 className="text-base font-semibold text-[var(--color-text)] mb-1">
        {title}
      </h3>
      {description && (
        <p className="text-sm text-[var(--color-text-muted)] max-w-sm mb-4">
          {description}
        </p>
      )}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
