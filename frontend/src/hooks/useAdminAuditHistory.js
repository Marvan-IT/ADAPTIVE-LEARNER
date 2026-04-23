import { useState, useEffect, useCallback } from "react";
import { getChanges, undoChange, redoChange } from "../api/admin";

/**
 * Fetches the admin audit change history and exposes undo/redo operations.
 *
 * @param {string|null} bookSlug  - Optional book filter; pass null for all books.
 * @param {number}      refreshTrigger - Increment this to force a refresh from outside.
 */
export function useAdminAuditHistory(bookSlug = null, refreshTrigger = 0) {
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = bookSlug ? { book_slug: bookSlug } : {};
      const { data } = await getChanges(params);
      setEntries(Array.isArray(data) ? data : []);
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  }, [bookSlug]);

  // Fetch on mount and whenever bookSlug or refreshTrigger changes
  useEffect(() => {
    refresh();
  }, [refresh, refreshTrigger]);

  // Entries come pre-sorted by created_at DESC from the server (limit=50).
  // Most recent active (not undone) entry — candidate for undo
  const lastActive = entries.find((e) => e.undone_at === null) ?? null;
  // Most recent undone entry — candidate for redo
  const lastUndone = entries.find((e) => e.undone_at !== null) ?? null;

  const canUndo = lastActive !== null;
  const canRedo = lastUndone !== null;

  /**
   * Undo a specific audit entry by id.
   * Calls onSuccess(responseData) on success or onStale(message) on 409.
   * Throws on other errors so callers can show generic error toasts.
   */
  const undo = useCallback(
    async (id, onSuccess, onStale) => {
      try {
        const { data } = await undoChange(id);
        await refresh();
        onSuccess?.(data);
      } catch (e) {
        if (e.response?.status === 409) {
          await refresh();
          onStale?.(e.response.data?.detail ?? "Resource was modified. Refresh and try again.");
        }
        throw e;
      }
    },
    [refresh]
  );

  /**
   * Redo a specific audit entry by id.
   * Same callback contract as undo().
   */
  const redo = useCallback(
    async (id, onSuccess, onStale) => {
      try {
        const { data } = await redoChange(id);
        await refresh();
        onSuccess?.(data);
      } catch (e) {
        if (e.response?.status === 409) {
          await refresh();
          onStale?.(e.response.data?.detail ?? "Resource was modified since undo. Refresh and try again.");
        }
        throw e;
      }
    },
    [refresh]
  );

  return {
    entries,
    loading,
    error,
    canUndo,
    canRedo,
    lastActive,
    lastUndone,
    undo,
    redo,
    refresh,
  };
}
