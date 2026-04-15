import { useState } from "react";
import { cn } from "./lib/utils";

/** @type {string[]} */
const PALETTE = [
  "bg-orange-500",
  "bg-blue-500",
  "bg-green-500",
  "bg-purple-500",
  "bg-pink-500",
  "bg-cyan-500",
  "bg-amber-500",
  "bg-rose-500",
];

/** @type {Record<string, string>} */
const SIZE_CLASSES = {
  sm: "size-7 text-xs",
  md: "size-9 text-sm",
  lg: "size-12 text-base",
};

/**
 * Deterministic integer hash for a name string.
 * @param {string} name
 * @returns {number}
 */
function hashName(name) {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash);
  }
  return Math.abs(hash);
}

/**
 * Extracts up to two initials from a display name.
 * "John Doe" → "JD", "Madonna" → "M"
 * @param {string} name
 * @returns {string}
 */
function getInitials(name) {
  if (!name) return "?";
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return parts[0][0].toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

/**
 * User avatar — shows an image when available, falls back to colored initials.
 *
 * @param {{
 *   name: string,
 *   src?: string,
 *   size?: "sm" | "md" | "lg",
 *   className?: string
 * }} props
 * @param {string}           props.name  - Display name (used for initials and background color)
 * @param {string}           [props.src] - Optional image URL
 * @param {"sm"|"md"|"lg"}  [props.size="md"]
 * @param {string}           [props.className]
 */
export default function Avatar({ name = "", src, size = "md", className }) {
  const [imgError, setImgError] = useState(false);

  const sizeClass = SIZE_CLASSES[size] ?? SIZE_CLASSES.md;
  const bgClass = PALETTE[hashName(name) % PALETTE.length];
  const initials = getInitials(name);

  const baseClasses = cn(
    "rounded-[var(--radius-full)] inline-flex items-center justify-center font-bold text-white select-none shrink-0",
    sizeClass,
    className
  );

  // Render image when src is provided and hasn't errored
  if (src && !imgError) {
    return (
      <img
        src={src}
        alt={name}
        className={cn(baseClasses, "object-cover")}
        onError={() => setImgError(true)}
      />
    );
  }

  // Initials fallback
  return (
    <div className={cn(baseClasses, bgClass)} aria-label={name} role="img">
      {initials}
    </div>
  );
}
