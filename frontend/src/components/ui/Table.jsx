import { ChevronDown, ChevronUp, ChevronsUpDown } from "lucide-react";
import { cn } from "./lib/utils";
import { TableSkeleton } from "./Skeleton";
import Button from "./Button";

// ── Table ────────────────────────────────────────────────────────────────────
/**
 * @param {string}          [props.className]
 * @param {React.ReactNode} props.children
 */
export function Table({ className, children }) {
  return (
    <table className={cn("w-full border-collapse text-sm", className)}>
      {children}
    </table>
  );
}

// ── TableHead ────────────────────────────────────────────────────────────────
/**
 * @param {string}          [props.className]
 * @param {React.ReactNode} props.children
 */
export function TableHead({ className, children }) {
  return <thead className={cn(className)}>{children}</thead>;
}

// ── TableBody ────────────────────────────────────────────────────────────────
/**
 * @param {string}          [props.className]
 * @param {React.ReactNode} props.children
 */
export function TableBody({ className, children }) {
  return <tbody className={cn(className)}>{children}</tbody>;
}

// ── TableRow ─────────────────────────────────────────────────────────────────
/**
 * @param {string}          [props.className]
 * @param {React.ReactNode} props.children
 * @param {boolean}         [props.hoverable=true]
 */
export function TableRow({ className, children, hoverable = true }) {
  return (
    <tr
      className={cn(
        "transition-colors",
        hoverable && "hover:bg-[color-mix(in_srgb,var(--color-primary)_5%,transparent)]",
        className
      )}
    >
      {children}
    </tr>
  );
}

// ── TableHeaderCell ───────────────────────────────────────────────────────────
/**
 * @param {string}              [props.className]
 * @param {React.ReactNode}     props.children
 * @param {boolean}             [props.sortable]
 * @param {"asc"|"desc"|null}   [props.sortDir]
 * @param {function}            [props.onSort]
 */
export function TableHeaderCell({
  className,
  children,
  sortable = false,
  sortDir = null,
  onSort,
}) {
  const SortIcon =
    sortDir === "asc"
      ? ChevronUp
      : sortDir === "desc"
      ? ChevronDown
      : ChevronsUpDown;

  return (
    <th
      className={cn(
        "px-3 py-2.5 text-start text-[11px] font-semibold uppercase tracking-wider",
        "text-[var(--color-text-muted)] bg-[var(--table-header-bg)]",
        "select-none whitespace-nowrap",
        sortable && "cursor-pointer",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)] focus-visible:ring-inset",
        className
      )}
      onClick={sortable ? onSort : undefined}
      onKeyDown={
        sortable
          ? (e) => (e.key === "Enter" || e.key === " ") && onSort?.()
          : undefined
      }
      tabIndex={sortable ? 0 : undefined}
      aria-sort={
        sortable
          ? sortDir === "asc"
            ? "ascending"
            : sortDir === "desc"
            ? "descending"
            : "none"
          : undefined
      }
    >
      <span className="inline-flex items-center gap-1">
        {children}
        {sortable && (
          <SortIcon
            size={13}
            className={cn(
              "shrink-0 transition-opacity",
              sortDir ? "opacity-80" : "opacity-40"
            )}
            aria-hidden="true"
          />
        )}
      </span>
    </th>
  );
}

// ── TableCell ─────────────────────────────────────────────────────────────────
/**
 * @param {string}          [props.className]
 * @param {React.ReactNode} props.children
 */
export function TableCell({ className, children }) {
  return (
    <td
      className={cn(
        "px-3 py-2.5 text-sm border-b border-[var(--color-border)]",
        className
      )}
    >
      {children}
    </td>
  );
}

// ── SortableTable ─────────────────────────────────────────────────────────────
/**
 * Convenience wrapper that renders a full sortable, paginated table.
 *
 * @param {Array<{key:string, label:string, sortable?:boolean, render?:function, className?:string}>} props.columns
 * @param {Array<object>}  props.data
 * @param {string}         [props.sortKey]
 * @param {"asc"|"desc"}   [props.sortDir]
 * @param {function}       [props.onSort]           - called with column key
 * @param {boolean}        [props.loading]
 * @param {string}         [props.emptyMessage="No data"]
 * @param {React.ReactNode}[props.emptyIcon]
 * @param {{ page:number, pageSize:number, total:number, onPageChange:function }} [props.pagination]
 * @param {boolean}        [props.striped=true]
 * @param {boolean}        [props.hoverable=true]
 * @param {string}         [props.className]
 */
export function SortableTable({
  columns = [],
  data = [],
  sortKey,
  sortDir,
  onSort,
  loading = false,
  emptyMessage = "No data",
  emptyIcon,
  pagination,
  striped = true,
  hoverable = true,
  className,
}) {
  if (loading) {
    return (
      <TableSkeleton
        rows={5}
        cols={columns.length || 4}
        className={className}
      />
    );
  }

  const totalPages = pagination
    ? Math.ceil(pagination.total / pagination.pageSize)
    : 1;
  const showStart = pagination
    ? (pagination.page - 1) * pagination.pageSize + 1
    : 1;
  const showEnd = pagination
    ? Math.min(pagination.page * pagination.pageSize, pagination.total)
    : data.length;

  return (
    <div className={cn("w-full", className)}>
      <div className="overflow-x-auto rounded-2xl overflow-hidden border border-[var(--color-border)]">
        <Table>
          <TableHead>
            <TableRow hoverable={false}>
              {columns.map((col) => (
                <TableHeaderCell
                  key={col.key}
                  sortable={col.sortable}
                  sortDir={sortKey === col.key ? sortDir : null}
                  onSort={col.sortable ? () => onSort?.(col.key) : undefined}
                  className={col.className}
                >
                  {col.label}
                </TableHeaderCell>
              ))}
            </TableRow>
          </TableHead>

          <TableBody>
            {data.length === 0 ? (
              <tr>
                <td colSpan={columns.length}>
                  <div className="flex flex-col items-center justify-center gap-3 py-12 text-[var(--color-text-muted)]">
                    {emptyIcon && (
                      <span className="opacity-40 [&>svg]:size-8">
                        {emptyIcon}
                      </span>
                    )}
                    <span className="text-sm">{emptyMessage}</span>
                  </div>
                </td>
              </tr>
            ) : (
              data.map((row, rowIdx) => (
                <TableRow
                  key={row.id ?? rowIdx}
                  hoverable={hoverable}
                  className={
                    striped && rowIdx % 2 === 1
                      ? "bg-[var(--table-stripe)]"
                      : undefined
                  }
                >
                  {columns.map((col) => (
                    <TableCell key={col.key} className={col.className}>
                      {col.render ? col.render(row) : row[col.key]}
                    </TableCell>
                  ))}
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {pagination && (
        <div className="flex items-center justify-between px-3 py-3 border-t border-[var(--color-border)]">
          <span className="text-sm text-[var(--color-text-muted)]">
            {pagination.total === 0
              ? "No results"
              : `Showing ${showStart} to ${showEnd} of ${pagination.total}`}
          </span>
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              disabled={pagination.page <= 1}
              onClick={() => pagination.onPageChange(pagination.page - 1)}
            >
              Previous
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled={pagination.page >= totalPages}
              onClick={() => pagination.onPageChange(pagination.page + 1)}
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
