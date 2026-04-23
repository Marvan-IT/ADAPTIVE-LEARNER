import { useState } from "react";
import { Undo2, Redo2 } from "lucide-react";
import { useAdminAuditHistory } from "../../hooks/useAdminAuditHistory";
import { useAdminKeyboardShortcuts } from "../../hooks/useAdminKeyboardShortcuts";
import { useToast } from "../ui/Toast";
import { Modal, ModalHeader, ModalBody, ModalFooter } from "../ui/Modal";
import { Button } from "../ui/Button";

// Action types that require a confirmation dialog before undo/redo because
// they involve structural DB changes that are harder to reverse cleanly.
const HARD_ACTIONS = new Set(["merge_chunks", "split_chunk", "promote"]);

// Maps raw action_type strings to human-readable labels for toasts.
const ACTION_LABELS = {
  update_chunk: "Edit chunk",
  toggle_chunk_visibility: "Toggle chunk visibility",
  toggle_chunk_exam_gate: "Toggle chunk exam gate",
  rename_section: "Rename section",
  toggle_section_optional: "Toggle section optional",
  toggle_section_exam_gate: "Toggle section exam gate",
  toggle_section_visibility: "Toggle section visibility",
  reorder_chunks: "Reorder chunks",
  merge_chunks: "Merge chunks",
  split_chunk: "Split chunk",
  promote: "Promote subsection",
};

function humanize(actionType) {
  return ACTION_LABELS[actionType] ?? actionType;
}

/**
 * Renders two icon buttons (Undo / Redo) for the admin top-bar.
 *
 * @param {string|null}   bookSlug      - Filters audit history to this book.
 * @param {function}      onAfterUndo   - Called after a successful undo so the parent can refresh.
 * @param {function}      onAfterRedo   - Called after a successful redo so the parent can refresh.
 * @param {number}        refreshTrigger - Increment externally to re-fetch audit history.
 */
export function UndoRedoControls({ bookSlug = null, onAfterUndo, onAfterRedo, refreshTrigger = 0 }) {
  const { toast } = useToast();
  const {
    canUndo,
    canRedo,
    lastActive,
    lastUndone,
    undo,
    redo,
  } = useAdminAuditHistory(bookSlug, refreshTrigger);

  // null | 'undo' | 'redo' — controls the confirmation modal for hard actions
  const [confirming, setConfirming] = useState(null);
  const [busy, setBusy] = useState(false);

  // ── Execute undo ─────────────────────────────────────────────────────────

  const executeUndo = async (id) => {
    setBusy(true);
    try {
      await undo(
        id,
        (data) => {
          toast({
            variant: "success",
            title: `Undone: ${humanize(data.action_type)}`,
          });
          onAfterUndo?.();
        },
        (msg) => {
          toast({
            variant: "warning",
            title: "Cannot undo",
            description: msg ?? "Resource was modified by someone else. Please refresh.",
          });
        }
      );
    } catch (e) {
      const status = e.response?.status;
      if (status === 400) {
        toast({ variant: "danger", title: "Already undone", description: "This action was already undone." });
      } else if (status === 403) {
        toast({ variant: "danger", title: "Permission denied", description: "You can only undo your own actions." });
      } else if (status === 404) {
        toast({ variant: "danger", title: "Not found", description: "Audit entry no longer exists." });
      } else {
        toast({ variant: "danger", title: "Undo failed", description: "Please try again." });
      }
    } finally {
      setBusy(false);
      setConfirming(null);
    }
  };

  // ── Execute redo ─────────────────────────────────────────────────────────

  const executeRedo = async (id) => {
    setBusy(true);
    try {
      await redo(
        id,
        (data) => {
          toast({
            variant: "success",
            title: `Redone: ${humanize(data.action_type)}`,
          });
          onAfterRedo?.();
        },
        (msg) => {
          toast({
            variant: "warning",
            title: "Cannot redo",
            description: msg ?? "Resource was modified since undo. Please refresh.",
          });
        }
      );
    } catch (e) {
      const status = e.response?.status;
      if (status === 400) {
        toast({ variant: "danger", title: "Not undone yet", description: "Cannot redo an action that hasn't been undone." });
      } else if (status === 403) {
        toast({ variant: "danger", title: "Permission denied", description: "You can only redo your own actions." });
      } else if (status === 404) {
        toast({ variant: "danger", title: "Not found", description: "Audit entry no longer exists." });
      } else {
        toast({ variant: "danger", title: "Redo failed", description: "Please try again." });
      }
    } finally {
      setBusy(false);
      setConfirming(null);
    }
  };

  // ── Intent handlers (check for hard actions first) ────────────────────────

  const handleUndo = () => {
    if (!lastActive) return;
    if (HARD_ACTIONS.has(lastActive.action_type)) {
      setConfirming("undo");
      return;
    }
    executeUndo(lastActive.id);
  };

  const handleRedo = () => {
    if (!lastUndone) return;
    if (HARD_ACTIONS.has(lastUndone.action_type)) {
      setConfirming("redo");
      return;
    }
    executeRedo(lastUndone.id);
  };

  // Wire keyboard shortcuts
  useAdminKeyboardShortcuts({
    onUndo: handleUndo,
    onRedo: handleRedo,
    canUndo,
    canRedo,
  });

  // ── Confirmation dialog data ──────────────────────────────────────────────

  const confirmingEntry = confirming === "undo" ? lastActive : lastUndone;
  const confirmingLabel = confirming === "undo" ? "Undo" : "Redo";
  const confirmingAction = confirming === "undo"
    ? () => executeUndo(lastActive?.id)
    : () => executeRedo(lastUndone?.id);

  // ── Shared button styles ──────────────────────────────────────────────────

  const btnBase = {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    width: "32px",
    height: "32px",
    borderRadius: "8px",
    border: "1px solid #E2E8F0",
    backgroundColor: "#FFFFFF",
    cursor: "pointer",
    transition: "background-color 0.15s, border-color 0.15s",
  };

  const btnDisabled = {
    opacity: 0.4,
    cursor: "not-allowed",
    pointerEvents: "none",
  };

  const btnActive = {
    color: "var(--color-primary)",
  };

  return (
    <>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "4px",
        }}
        aria-label="Undo/Redo controls"
      >
        <button
          onClick={handleUndo}
          disabled={!canUndo || busy}
          title="Undo (Ctrl+Z)"
          aria-label="Undo last action"
          style={{
            ...btnBase,
            ...(canUndo && !busy ? btnActive : {}),
            ...(!canUndo || busy ? btnDisabled : {}),
          }}
        >
          <Undo2 size={16} aria-hidden="true" />
        </button>

        <button
          onClick={handleRedo}
          disabled={!canRedo || busy}
          title="Redo (Ctrl+Shift+Z)"
          aria-label="Redo last undone action"
          style={{
            ...btnBase,
            ...(canRedo && !busy ? btnActive : {}),
            ...(!canRedo || busy ? btnDisabled : {}),
          }}
        >
          <Redo2 size={16} aria-hidden="true" />
        </button>
      </div>

      {/* Confirmation dialog for hard (destructive) actions */}
      <Modal
        open={confirming !== null}
        onClose={() => !busy && setConfirming(null)}
        size="sm"
      >
        <ModalHeader>Confirm {confirmingLabel}</ModalHeader>
        <ModalBody>
          <p style={{ fontSize: "14px", color: "var(--color-text)", lineHeight: 1.6, margin: 0 }}>
            This will {confirming === "undo" ? "undo" : "redo"} a{" "}
            <strong>{humanize(confirmingEntry?.action_type)}</strong> operation.
            Affected teaching sessions may see changes immediately.
          </p>
          <p style={{ fontSize: "13px", color: "var(--color-text-muted)", marginTop: "10px", marginBottom: 0 }}>
            This action involves structural content changes. Are you sure you want to proceed?
          </p>
        </ModalBody>
        <ModalFooter>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setConfirming(null)}
            disabled={busy}
          >
            Cancel
          </Button>
          <Button
            variant="danger"
            size="sm"
            loading={busy}
            onClick={confirmingAction}
          >
            {confirmingLabel}
          </Button>
        </ModalFooter>
      </Modal>
    </>
  );
}
