import { createContext, useContext, useState, useCallback, useRef } from "react";
import { Modal, ModalHeader, ModalBody, ModalFooter } from "../components/ui/Modal";
import Button from "../components/ui/Button";

const DialogContext = createContext(null);

export function useDialog() {
  return useContext(DialogContext);
}

export function DialogProvider({ children }) {
  const [state, setState] = useState({ open: false, title: "", message: "", confirmLabel: "OK", cancelLabel: "Cancel", variant: "primary" });
  const resolverRef = useRef(null);

  const confirm = useCallback(({ title = "Confirm", message, confirmLabel = "OK", cancelLabel = "Cancel", variant = "primary" } = {}) => {
    return new Promise((resolve) => {
      resolverRef.current = resolve;
      setState({ open: true, title, message, confirmLabel, cancelLabel, variant });
    });
  }, []);

  const handleConfirm = useCallback(() => {
    resolverRef.current?.(true);
    setState((s) => ({ ...s, open: false }));
  }, []);

  const handleCancel = useCallback(() => {
    resolverRef.current?.(false);
    setState((s) => ({ ...s, open: false }));
  }, []);

  return (
    <DialogContext.Provider value={{ confirm }}>
      {children}
      <Modal open={state.open} onClose={handleCancel} size="sm">
        <ModalHeader>{state.title}</ModalHeader>
        <ModalBody>
          <p style={{ fontSize: "0.875rem", color: "var(--color-text-muted)", lineHeight: 1.6, whiteSpace: "pre-line" }}>
            {state.message}
          </p>
        </ModalBody>
        <ModalFooter>
          <Button variant="secondary" size="sm" onClick={handleCancel}>
            {state.cancelLabel}
          </Button>
          <Button variant={state.variant === "danger" ? "danger" : "primary"} size="sm" onClick={handleConfirm}>
            {state.confirmLabel}
          </Button>
        </ModalFooter>
      </Modal>
    </DialogContext.Provider>
  );
}
