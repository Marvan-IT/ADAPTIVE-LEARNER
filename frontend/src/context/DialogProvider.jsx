import { createContext, useContext, useState, useCallback, useRef } from "react";
import { Modal, ModalHeader, ModalBody, ModalFooter } from "../components/ui/Modal";
import Button from "../components/ui/Button";

const DialogContext = createContext(null);

export function useDialog() {
  return useContext(DialogContext);
}

export function DialogProvider({ children }) {
  const [confirmState, setConfirmState] = useState({ open: false, title: "", message: "", confirmLabel: "OK", cancelLabel: "Cancel", variant: "primary" });
  const [promptState, setPromptState] = useState({ open: false, title: "", defaultValue: "", cancelLabel: "Cancel", confirmLabel: "OK" });
  const [promptValue, setPromptValue] = useState("");
  const confirmResolverRef = useRef(null);
  const promptResolverRef = useRef(null);

  const confirm = useCallback(({ title = "Confirm", message, confirmLabel = "OK", cancelLabel = "Cancel", variant = "primary" } = {}) => {
    return new Promise((resolve) => {
      confirmResolverRef.current = resolve;
      setConfirmState({ open: true, title, message, confirmLabel, cancelLabel, variant });
    });
  }, []);

  const prompt = useCallback(({ title = "", defaultValue = "", confirmLabel = "OK", cancelLabel = "Cancel" } = {}) => {
    return new Promise((resolve) => {
      promptResolverRef.current = resolve;
      setPromptValue(defaultValue);
      setPromptState({ open: true, title, defaultValue, confirmLabel, cancelLabel });
    });
  }, []);

  const handleConfirm = useCallback(() => {
    confirmResolverRef.current?.(true);
    setConfirmState((s) => ({ ...s, open: false }));
  }, []);

  const handleCancel = useCallback(() => {
    confirmResolverRef.current?.(false);
    setConfirmState((s) => ({ ...s, open: false }));
  }, []);

  const handlePromptConfirm = useCallback(() => {
    promptResolverRef.current?.(promptValue);
    setPromptState((s) => ({ ...s, open: false }));
  }, [promptValue]);

  const handlePromptCancel = useCallback(() => {
    promptResolverRef.current?.(null);
    setPromptState((s) => ({ ...s, open: false }));
  }, []);

  return (
    <DialogContext.Provider value={{ confirm, prompt }}>
      {children}

      {/* Confirm dialog */}
      <Modal open={confirmState.open} onClose={handleCancel} size="md">
        <ModalHeader>{confirmState.title}</ModalHeader>
        <ModalBody>
          <p style={{ fontSize: "0.9375rem", color: "var(--color-text-muted)", lineHeight: 1.6, whiteSpace: "pre-line" }}>
            {confirmState.message}
          </p>
        </ModalBody>
        <ModalFooter>
          <Button variant="secondary" size="md" onClick={handleCancel} className="min-w-[96px] whitespace-nowrap">
            {confirmState.cancelLabel}
          </Button>
          <Button variant={confirmState.variant === "danger" ? "danger" : "primary"} size="md" onClick={handleConfirm} className="min-w-[96px] whitespace-nowrap">
            {confirmState.confirmLabel}
          </Button>
        </ModalFooter>
      </Modal>

      {/* Prompt dialog */}
      <Modal open={promptState.open} onClose={handlePromptCancel} size="md">
        <ModalHeader>{promptState.title}</ModalHeader>
        <ModalBody>
          <input
            autoFocus
            type="text"
            value={promptValue}
            onChange={(e) => setPromptValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handlePromptConfirm();
              if (e.key === "Escape") handlePromptCancel();
            }}
            style={{
              width: "100%",
              padding: "8px 12px",
              fontSize: "0.9375rem",
              border: "1.5px solid var(--color-border, #E2E8F0)",
              borderRadius: "8px",
              outline: "none",
              boxSizing: "border-box",
              color: "var(--color-text, #0F172A)",
              background: "var(--color-surface, #FFFFFF)",
            }}
          />
        </ModalBody>
        <ModalFooter>
          <Button variant="secondary" size="md" onClick={handlePromptCancel} className="min-w-[96px] whitespace-nowrap">
            {promptState.cancelLabel}
          </Button>
          <Button variant="primary" size="md" onClick={handlePromptConfirm} className="min-w-[96px] whitespace-nowrap">
            {promptState.confirmLabel}
          </Button>
        </ModalFooter>
      </Modal>
    </DialogContext.Provider>
  );
}
