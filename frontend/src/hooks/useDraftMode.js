import { useState, useEffect, useCallback, useRef } from "react";

function computeHash(serverChunks) {
  return JSON.stringify((serverChunks || []).map((c) => c.id)).slice(0, 100);
}

function storageKey(slug, conceptId) {
  return `content-draft:${slug}:${conceptId}`;
}

function loadFromStorage(slug, conceptId, serverChunks) {
  if (!slug || !conceptId) return null;
  try {
    const raw = localStorage.getItem(storageKey(slug, conceptId));
    if (!raw) return null;
    const saved = JSON.parse(raw);
    if (saved.hash !== computeHash(serverChunks)) return null;
    return saved;
  } catch {
    return null;
  }
}

function persistToStorage(slug, conceptId, serverChunks, draftChunks, pendingStructural) {
  if (!slug || !conceptId) return;
  try {
    localStorage.setItem(
      storageKey(slug, conceptId),
      JSON.stringify({
        hash: computeHash(serverChunks),
        draftChunks,
        pendingStructural,
      })
    );
  } catch {
    // localStorage may be full; silently ignore
  }
}

function clearFromStorage(slug, conceptId) {
  if (!slug || !conceptId) return;
  try {
    localStorage.removeItem(storageKey(slug, conceptId));
  } catch {
    // ignore
  }
}

function isDraftDirty(draftChunks, serverChunks, pendingStructural) {
  if (pendingStructural.length > 0) return true;
  if (!draftChunks || !serverChunks) return false;
  if (draftChunks.length !== serverChunks.length) return true;
  return JSON.stringify(draftChunks) !== JSON.stringify(serverChunks);
}

const TRACKED_PROPS = ["heading", "text", "is_hidden", "is_optional", "exam_disabled", "chunk_type"];

function computeModifiedChunkIds(draftChunks, serverChunks) {
  const modified = new Set();
  const serverMap = new Map((serverChunks || []).map((c) => [c.id, c]));

  (draftChunks || []).forEach((draft) => {
    const isTempId = String(draft.id).startsWith("temp-");
    if (isTempId) {
      modified.add(draft.id);
      return;
    }
    const server = serverMap.get(draft.id);
    if (!server) {
      modified.add(draft.id);
      return;
    }
    const changed = TRACKED_PROPS.some((prop) => draft[prop] !== server[prop]);
    if (changed) modified.add(draft.id);
  });

  return modified;
}

export default function useDraftMode(slug, conceptId, serverChunks) {
  const [draftChunks, setDraftChunks] = useState([]);
  const [pendingStructural, setPendingStructural] = useState([]);
  const [saveStatus, setSaveStatus] = useState(null);

  // Track previous conceptId to detect section changes
  const prevConceptIdRef = useRef(null);
  const serverChunksRef = useRef(serverChunks);
  serverChunksRef.current = serverChunks;

  // When conceptId or serverChunks change, try restoring draft or copy serverChunks
  useEffect(() => {
    if (!conceptId || !serverChunks) {
      setDraftChunks([]);
      setPendingStructural([]);
      prevConceptIdRef.current = conceptId;
      return;
    }

    const saved = loadFromStorage(slug, conceptId, serverChunks);
    if (saved) {
      setDraftChunks(saved.draftChunks);
      setPendingStructural(saved.pendingStructural || []);
    } else {
      setDraftChunks([...serverChunks]);
      setPendingStructural([]);
    }

    prevConceptIdRef.current = conceptId;
  }, [slug, conceptId, serverChunks]); // eslint-disable-line react-hooks/exhaustive-deps

  // Derived values
  const isDirty = isDraftDirty(draftChunks, serverChunks, pendingStructural);
  const modifiedChunkIds = computeModifiedChunkIds(draftChunks, serverChunks);

  // Navigation guard
  useEffect(() => {
    if (!isDirty) return;
    const handler = (e) => {
      e.preventDefault();
      e.returnValue = "You have unsaved changes. Are you sure you want to leave?";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [isDirty]);

  // ── Edit a chunk in draft ──────────────────────────────────────────────

  const editChunk = useCallback((chunkId, changes) => {
    setDraftChunks((prev) => {
      const next = prev.map((c) => (c.id === chunkId ? { ...c, ...changes } : c));
      persistToStorage(slug, conceptId, serverChunksRef.current, next, pendingStructural);
      return next;
    });
  }, [slug, conceptId, pendingStructural]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Merge two consecutive chunks in draft ─────────────────────────────

  const mergeDraftChunks = useCallback((id1, id2) => {
    setDraftChunks((prev) => {
      const idx1 = prev.findIndex((c) => c.id === id1);
      const idx2 = prev.findIndex((c) => c.id === id2);
      if (idx1 === -1 || idx2 === -1) return prev;
      const chunk1 = prev[idx1];
      const chunk2 = prev[idx2];
      const merged = {
        ...chunk1,
        text: (chunk1.text || "") + "\n\n" + (chunk2.text || ""),
      };
      const next = prev
        .map((c) => (c.id === id1 ? merged : c))
        .filter((c) => c.id !== id2);
      setPendingStructural((ps) => {
        const updated = [...ps, { type: "merge", chunk1Id: id1, chunk2Id: id2 }];
        persistToStorage(slug, conceptId, serverChunksRef.current, next, updated);
        return updated;
      });
      return next;
    });
  }, [slug, conceptId]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Split a chunk at a character position in draft ────────────────────

  const splitDraftChunk = useCallback((chunkId, position) => {
    setDraftChunks((prev) => {
      const idx = prev.findIndex((c) => c.id === chunkId);
      if (idx === -1) return prev;
      const original = prev[idx];
      const textBefore = (original.text || "").slice(0, position);
      const textAfter = (original.text || "").slice(position);
      const tempId = "temp-" + Date.now() + "-" + Math.random().toString(36).slice(2, 8);
      const updatedOriginal = { ...original, text: textBefore };
      const newChunk = {
        ...original,
        id: tempId,
        text: textAfter,
        heading: "",
      };
      const next = [
        ...prev.slice(0, idx),
        updatedOriginal,
        newChunk,
        ...prev.slice(idx + 1),
      ];
      setPendingStructural((ps) => {
        const updated = [...ps, { type: "split", chunkId, position, tempId }];
        persistToStorage(slug, conceptId, serverChunksRef.current, next, updated);
        return updated;
      });
      return next;
    });
  }, [slug, conceptId]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Discard all draft changes ──────────────────────────────────────────

  const discardDraft = useCallback(() => {
    setDraftChunks([...(serverChunksRef.current || [])]);
    setPendingStructural([]);
    clearFromStorage(slug, conceptId);
    setSaveStatus(null);
  }, [slug, conceptId]);

  // ── Save draft: execute structural ops then update modified chunks ─────

  const saveDraft = useCallback(async (apiCallbacks) => {
    const {
      updateChunk,
      mergeChunks,
      splitChunk,
      reloadChunks,
    } = apiCallbacks;

    setSaveStatus("saving");

    try {
      // Step 1: Execute structural operations in order
      for (const op of pendingStructural) {
        if (op.type === "split") {
          const isTempSource = String(op.chunkId).startsWith("temp-");
          if (!isTempSource) {
            await splitChunk(op.chunkId, op.position);
          }
        } else if (op.type === "merge") {
          const isTemp1 = String(op.chunk1Id).startsWith("temp-");
          const isTemp2 = String(op.chunk2Id).startsWith("temp-");
          if (!isTemp1 && !isTemp2) {
            await mergeChunks(op.chunk1Id, op.chunk2Id);
          }
        }
      }

      // Step 2: Reload to get fresh real IDs from DB
      const freshChunks = await reloadChunks();
      const freshList = Array.isArray(freshChunks) ? freshChunks : [];

      // Step 3: Build a position-based map to match draft chunks to real chunks
      // We match by position index since structural ops may have changed IDs
      const currentDraft = draftChunks;
      const nonTempDraft = currentDraft.filter((c) => !String(c.id).startsWith("temp-"));

      // Match real chunks to draft chunks by index for non-temp entries
      const serverMap = new Map((serverChunksRef.current || []).map((c) => [c.id, c]));
      const modIds = computeModifiedChunkIds(currentDraft, serverChunksRef.current);

      for (const draftChunk of currentDraft) {
        const isTempId = String(draftChunk.id).startsWith("temp-");

        // For real (non-temp) chunks that were modified, find them in fresh list and update
        if (!isTempId && modIds.has(draftChunk.id)) {
          const realChunk = freshList.find((fc) => fc.id === draftChunk.id);
          const realId = realChunk ? realChunk.id : draftChunk.id;
          const serverVersion = serverMap.get(draftChunk.id);
          const changedProps = {};
          TRACKED_PROPS.forEach((prop) => {
            if (!serverVersion || draftChunk[prop] !== serverVersion[prop]) {
              changedProps[prop] = draftChunk[prop];
            }
          });
          if (Object.keys(changedProps).length > 0) {
            await updateChunk(realId, changedProps);
          }
        }

        // For temp (split-result) chunks, find the matching new chunk in freshList by position
        if (isTempId) {
          const draftIdx = currentDraft.findIndex((c) => c.id === draftChunk.id);
          // The split already ran, so freshList should have a chunk at roughly the same position
          const freshChunkAtPos = freshList[draftIdx] || freshList[freshList.length - 1];
          if (freshChunkAtPos) {
            const changedProps = {};
            TRACKED_PROPS.forEach((prop) => {
              if (draftChunk[prop] !== undefined) changedProps[prop] = draftChunk[prop];
            });
            if (Object.keys(changedProps).length > 0) {
              await updateChunk(freshChunkAtPos.id, changedProps);
            }
          }
        }
      }

      // Step 4: Clear draft state
      clearFromStorage(slug, conceptId);
      setPendingStructural([]);
      setSaveStatus("success");

      // Brief success indication then reset
      setTimeout(() => setSaveStatus(null), 2000);
    } catch (err) {
      setSaveStatus("error");
      throw err;
    }
  }, [slug, conceptId, pendingStructural, draftChunks]); // eslint-disable-line react-hooks/exhaustive-deps

  return {
    draftChunks,
    isDirty,
    modifiedChunkIds,
    pendingStructural,
    editChunk,
    mergeDraftChunks,
    splitDraftChunk,
    saveDraft,
    discardDraft,
    saveStatus,
  };
}
