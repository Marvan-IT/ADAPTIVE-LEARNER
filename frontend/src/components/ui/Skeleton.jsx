import { cn } from "./lib/utils";

/**
 * Base skeleton shimmer block.
 * @param {{ className?: string }} props
 * @param {string} [props.className] - Tailwind classes controlling width/height (e.g. "w-full h-4")
 */
export default function Skeleton({ className }) {
  return (
    <div
      className={cn("skeleton-shimmer h-4 w-full", className)}
      aria-hidden="true"
    />
  );
}

/**
 * A stack of skeleton text lines.
 * @param {{ lines?: number, className?: string }} props
 * @param {number} [props.lines=3] - Number of lines to render
 * @param {string} [props.className]
 */
export function TextSkeleton({ lines = 3, className }) {
  return (
    <div className={cn("space-y-2", className)} aria-hidden="true">
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          className={i === lines - 1 ? "w-3/4" : "w-full"}
        />
      ))}
    </div>
  );
}

/**
 * A card-shaped skeleton placeholder matching the Card component's proportions.
 * @param {{ className?: string }} props
 */
export function CardSkeleton({ className }) {
  return (
    <div
      className={cn(
        "rounded-[var(--radius-lg)] border border-[var(--color-border)] overflow-hidden p-6",
        className
      )}
      aria-hidden="true"
      aria-label="Loading card"
    >
      {/* Header: avatar circle + two title lines */}
      <div className="flex items-center gap-3 mb-5">
        <Skeleton className="size-10 rounded-[var(--radius-full)] shrink-0" />
        <div className="flex-1 space-y-2">
          <Skeleton className="h-4 w-1/2" />
          <Skeleton className="h-3 w-1/3" />
        </div>
      </div>

      {/* Content lines */}
      <div className="space-y-2 mb-6">
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-3/4" />
      </div>

      {/* Footer: two button-shaped skeletons */}
      <div className="flex gap-3">
        <Skeleton className="h-9 w-24 rounded-[var(--radius-full)]" />
        <Skeleton className="h-9 w-24 rounded-[var(--radius-full)]" />
      </div>
    </div>
  );
}

/**
 * A table-shaped skeleton placeholder.
 * @param {{ rows?: number, cols?: number, className?: string }} props
 * @param {number} [props.rows=5] - Number of data rows
 * @param {number} [props.cols=4] - Number of columns
 * @param {string} [props.className]
 */
export function TableSkeleton({ rows = 5, cols = 4, className }) {
  // Cycle through widths to give organic feel
  const colWidths = ["w-20", "w-28", "w-16", "w-24", "w-20", "w-32"];

  return (
    <table
      className={cn("w-full border-collapse", className)}
      aria-hidden="true"
    >
      <thead>
        <tr>
          {Array.from({ length: cols }).map((_, c) => (
            <th key={c} className="px-3 py-2">
              <Skeleton className={cn("h-3", colWidths[c % colWidths.length])} />
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {Array.from({ length: rows }).map((_, r) => (
          <tr key={r}>
            {Array.from({ length: cols }).map((_, c) => (
              <td key={c} className="px-3 py-2">
                <Skeleton
                  className={cn(
                    "h-4",
                    colWidths[(r + c + 1) % colWidths.length]
                  )}
                />
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/**
 * A large circular skeleton placeholder for the concept map / graph view.
 * @param {{ className?: string }} props
 */
export function GraphSkeleton({ className }) {
  return (
    <div className={cn("w-64 h-64 mx-auto rounded-full", className)} aria-hidden="true">
      <div className="skeleton-shimmer w-full h-full rounded-full" />
    </div>
  );
}
