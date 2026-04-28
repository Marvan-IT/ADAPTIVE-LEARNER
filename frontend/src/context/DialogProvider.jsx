import { createContext, useContext, useState, useCallback, useRef } from "react";
import { motion } from "framer-motion";
import { AlertTriangle } from "lucide-react";
import { Modal } from "../components/ui/Modal";
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

      {/* Confirm dialog — centered layout, deliberate decision moment */}
      <Modal open={confirmState.open} onClose={handleCancel} size="md">
        <div className="px-8 pt-7 pb-2 flex flex-col items-center text-center">
          {confirmState.variant === "danger" && (
            <motion.div
              initial={{ scale: 0.7, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{ duration: 0.2, delay: 0.08 }}
              style={{
                width: 48, height: 48, borderRadius: "50%",
                backgroundColor: "rgba(239, 68, 68, 0.1)",
                border: "1.5px solid rgba(239, 68, 68, 0.25)",
                display: "flex", alignItems: "center", justifyContent: "center",
                marginBottom: "12px",
              }}
            >
              <AlertTriangle size={22} color="var(--color-danger)" strokeWidth={2.25} />
            </motion.div>
          )}
          <h3 style={{
            fontSize: "1.125rem", fontWeight: 700, color: "var(--color-text)",
            letterSpacing: "-0.01em", margin: 0,
          }}>
            {confirmState.title}
          </h3>
        </div>
        <div className="px-8 py-3">
          <p style={{
            fontSize: "0.9375rem", color: "var(--color-text-muted)",
            lineHeight: 1.6, whiteSpace: "pre-line", textAlign: "center", margin: 0,
          }}>
            {confirmState.message}
          </p>
        </div>
        <div className="px-8 pt-5 pb-7 flex justify-center gap-3">
          <Button variant="secondary" size="lg" onClick={handleCancel} className="whitespace-nowrap" style={{ minWidth: 120 }}>
            {confirmState.cancelLabel}
          </Button>
          <Button variant={confirmState.variant === "danger" ? "danger" : "primary"} size="lg" onClick={handleConfirm} className="whitespace-nowrap" style={{ minWidth: 120 }}>
            {confirmState.confirmLabel}
          </Button>
        </div>
      </Modal>

      {/* Prompt dialog — centered title, input centered, same footer treatment */}
      <Modal open={promptState.open} onClose={handlePromptCancel} size="md">
        <div className="px-8 pt-7 pb-2 text-center">
          <h3 style={{
            fontSize: "1.125rem", fontWeight: 700, color: "var(--color-text)",
            letterSpacing: "-0.01em", margin: 0,
          }}>
            {promptState.title}
          </h3>
        </div>
        <div className="px-8 py-4">
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
              padding: "10px 12px",
              fontSize: "0.9375rem",
              border: "1.5px solid var(--color-border, #E2E8F0)",
              borderRadius: "8px",
              outline: "none",
              boxSizing: "border-box",
              color: "var(--color-text, #0F172A)",
              background: "var(--color-surface, #FFFFFF)",
            }}
          />
        </div>
        <div className="px-8 pt-3 pb-7 flex justify-center gap-3">
          <Button variant="secondary" size="lg" onClick={handlePromptCancel} className="whitespace-nowrap" style={{ minWidth: 120 }}>
            {promptState.cancelLabel}
          </Button>
          <Button variant="primary" size="lg" onClick={handlePromptConfirm} className="whitespace-nowrap" style={{ minWidth: 120 }}>
            {promptState.confirmLabel}
          </Button>
        </div>
      </Modal>
    </DialogContext.Provider>
  );
}
