import { ChevronRight } from "lucide-react";
import { cn } from "./lib/utils";

/**
 * Breadcrumb navigation trail.
 * @param {Object} props
 * @param {{ label: string, href?: string }[]} props.items - Breadcrumb segments
 * @param {string} [props.className]
 */
export default function Breadcrumb({ items, className }) {
  if (!items || items.length === 0) return null;

  return (
    <nav aria-label="Breadcrumb" className={cn("flex items-center gap-1 text-sm", className)}>
      <ol className="flex items-center gap-1">
        {items.map((item, i) => {
          const isLast = i === items.length - 1;
          return (
            <li key={i} className="flex items-center gap-1">
              {i > 0 && (
                <ChevronRight
                  className="text-[var(--color-text-muted)] opacity-50 shrink-0"
                  size={14}
                  aria-hidden="true"
                />
              )}
              {isLast && !item.onClick ? (
                <span
                  className="font-medium truncate max-w-[200px] text-[var(--color-text)]"
                  aria-current="page"
                >
                  {item.label}
                </span>
              ) : item.onClick ? (
                <button
                  type="button"
                  onClick={item.onClick}
                  className="font-medium truncate max-w-[200px] text-[var(--color-primary)] hover:text-[var(--color-primary-dark)] transition-colors bg-transparent border-none cursor-pointer p-0"
                >
                  {item.label}
                </button>
              ) : item.href ? (
                <a
                  href={item.href}
                  className="text-[var(--color-primary)] hover:text-[var(--color-primary-dark)] transition-colors truncate max-w-[200px]"
                >
                  {item.label}
                </a>
              ) : (
                <span className="font-medium truncate max-w-[200px] text-[var(--color-text-muted)]">
                  {item.label}
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
