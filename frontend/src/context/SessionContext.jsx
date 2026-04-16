import { createContext, useContext, useReducer, useCallback } from "react";
import i18n from "i18next";
import {
  startSession,
  assistStudent,
  completeCards,
  recordCardInteraction,
  generateChunkCards,
  generateChunkRecoveryCard,
  getChunkList,
  completeChunk,
  completeChunkItem as completeChunkItemAPI,
  evaluateChunkAnswers,
  switchStyle,
  updateSessionInterests,
} from "../api/sessions";
import { useAdaptiveStore } from '../store/adaptiveStore';
import { useStudent } from "./StudentContext";
import { useTheme } from "./ThemeContext";
import { trackEvent } from "../utils/analytics";

const SessionContext = createContext();

const initialState = {
  phase: "IDLE",
  session: null,
  conceptTitle: "",
  bookTitle: "",
  // Card-based learning
  cards: [],
  currentCardIndex: 0,
  maxReachedIndex: 0,
  cardAnswers: {},
  totalQuestions: 0,
  // AI assistant
  assistMessages: [],
  assistLoading: false,
  // Completion
  score: null,
  mastered: null,
  loading: false,
  error: null,
  // Adaptive card tracking
  idleTriggerCount: 0,
  adaptiveCardLoading: false,
  motivationalNote: null,
  performanceVsBaseline: null,
  // Adaptive transparency
  learningProfileSummary: null,
  adaptationApplied: null,
  conceptLocked: false,
  bestScore: null,
  // Rolling adaptive replace
  adaptiveCallInFlight: false,
  // Section tracking
  hasMoreConcepts: true,
  conceptsTotal: 0,
  conceptsCoveredCount: 0,
  // Per-card adaptive generation
  nextCardInFlight: false,
  // Chunk-based card loading
  currentChunkId: null,
  currentChunkIndex: 0,
  totalChunks: 0,
  // Chunk-based navigation (new flow)
  chunkList: [],
  chunkIndex: 0,
  nextChunkCards: null,
  nextChunkInFlight: false,
  // Chunk progress tracking
  chunkProgress: {},
  currentChunkMode: "NORMAL",
  allStudyComplete: false,
  modeJustChanged: false,
  // Per-chunk Q&A state
  chunkQuestions: [],
  chunkEvalResult: null,
};

// Valid phases: IDLE, LOADING, SELECTING_CHUNK, CARDS, CHUNK_QUESTIONS, COMPLETED

function sessionReducer(state, action) {
  switch (action.type) {
    case "START_LOADING":
      if (state.session?.concept_id) {
        localStorage.removeItem(`ada_session_${state.session.student_id}_${state.session.concept_id}`);
      }
      return { ...initialState, phase: "LOADING", loading: true };
    case "TRANSITION_LOADING":
      return { ...state, loading: true };
    case "SESSION_CREATED":
      if (action.payload?.concept_id) {
        localStorage.setItem(`ada_session_${action.payload.student_id}_${action.payload.concept_id}`, action.payload.id);
      }
      return { ...state, session: action.payload };
    case "CARDS_LOADED":
      return {
        ...state,
        cards: action.payload.cards,
        conceptTitle: action.payload.concept_title,
        bookTitle: action.payload.book_title || state.bookTitle,
        totalQuestions: action.payload.total_questions,
        phase: "CARDS",
        loading: false,
        hasMoreConcepts: action.payload.has_more_concepts ?? true,
        conceptsTotal: action.payload.concepts_total ?? 0,
        conceptsCoveredCount: action.payload.concepts_covered_count ?? 0,
      };
    case "NEXT_CARD": {
      const rawNext = state.currentCardIndex + 1;
      // Allow advancing to cards.length (one past the end) only when a per-card
      // fetch is in flight — the card will arrive and APPEND_NEXT_CARD will land
      // at exactly that index. Otherwise clamp to the last available card.
      const upperBound = state.nextCardInFlight ? state.cards.length : Math.max(0, state.cards.length - 1);
      const nextIndex = Math.min(rawNext, upperBound);
      return {
        ...state,
        currentCardIndex: nextIndex,
        maxReachedIndex: Math.max(state.maxReachedIndex, nextIndex),
        idleTriggerCount: 0,
        motivationalNote: null,
        performanceVsBaseline: null,
      };
    }
    case "PREV_CARD":
      return {
        ...state,
        currentCardIndex: Math.max(state.currentCardIndex - 1, 0),
      };
    case "CARD_ANSWERED":
      return {
        ...state,
        cardAnswers: {
          ...state.cardAnswers,
          [action.payload.questionId]: {
            answer: action.payload.answer,
            correct: action.payload.correct,
          },
        },
      };
    case "ASSIST_SENT":
      return {
        ...state,
        assistMessages: [
          ...state.assistMessages,
          { role: "user", content: action.payload },
        ],
        assistLoading: true,
      };
    case "ASSIST_RESPONDED":
      return {
        ...state,
        assistMessages: [
          ...state.assistMessages,
          { role: "assistant", content: action.payload },
        ],
        assistLoading: false,
      };
    case "IDLE_TRIGGERED":
      return { ...state, idleTriggerCount: state.idleTriggerCount + 1 };
    case "ADAPTIVE_CARD_LOADING":
      return { ...state, adaptiveCardLoading: true };
    case "ADAPTIVE_CARD_LOADED": {
      const newIndex = state.currentCardIndex + 1;
      return {
        ...state,
        cards: [...state.cards, action.payload.card],
        currentCardIndex: newIndex,
        maxReachedIndex: Math.max(state.maxReachedIndex, newIndex),
        adaptiveCardLoading: false,
        idleTriggerCount: 0,
        motivationalNote: action.payload.motivational_note ?? null,
        performanceVsBaseline: action.payload.performance_vs_baseline ?? null,
        learningProfileSummary: action.payload.learning_profile_summary ?? null,
        adaptationApplied: action.payload.adaptation_applied ?? null,
      };
    }
    case "ADAPTIVE_CALL_STARTED":
      return { ...state, adaptiveCallInFlight: true };

    case "ADAPTIVE_CALL_DONE":
      return { ...state, adaptiveCallInFlight: false };

    case "NEXT_CARD_FETCH_STARTED":
      return { ...state, nextCardInFlight: true };

    case "NEXT_CARD_FETCH_DONE":
      return { ...state, nextCardInFlight: false };

    case "APPEND_NEXT_CARD":
      return {
        ...state,
        cards: [...state.cards, action.payload.card],
        hasMoreConcepts: action.payload.has_more_concepts,
        nextCardInFlight: false,
      };

    case "REPLACE_UPCOMING_CARD": {
      const targetIndex = state.currentCardIndex + 1;
      const newCards = [...state.cards];
      if (targetIndex < newCards.length) {
        newCards[targetIndex] = { ...action.payload.card, index: targetIndex };
      } else {
        newCards.push({ ...action.payload.card, index: newCards.length });
      }
      return {
        ...state,
        cards: newCards,
        adaptiveCardLoading: false,
        adaptiveCallInFlight: false,
        motivationalNote: action.payload.motivational_note ?? null,
        learningProfileSummary: action.payload.learning_profile_summary ?? null,
        adaptationApplied: action.payload.adaptation_applied ?? null,
      };
    }

    case "INSERT_RECOVERY_CARD": {
      const insertAt = state.currentCardIndex + 1;
      const newCards = [
        ...state.cards.slice(0, insertAt),
        { ...action.payload, index: insertAt },
        ...state.cards.slice(insertAt).map((c, i) => ({
          ...c, index: insertAt + 1 + i,
        })),
      ];
      return {
        ...state,
        cards: newCards,
        maxReachedIndex: Math.max(state.maxReachedIndex, insertAt),
      };
    }

    case "CHUNK_CARDS_LOADED":
      return {
        ...state,
        cards: action.payload.cards,
        currentCardIndex: 0,
        currentChunkId: action.payload.chunk_id,
        currentChunkIndex: action.payload.chunk_index,
        totalChunks: action.payload.total_chunks,
        nextCardInFlight: false,
        cardAnswers: {},
        chunkEvalResult: null,
      };

    case "CHUNK_LOADING":
      return { ...state, loading: true, error: null, phase: "LOADING" };

    case "CHUNK_LIST_LOADED": {
      // Restore chunkProgress from completed chunks (needed for session resume)
      const _restored = {};
      for (const _ch of (action.payload.chunks || [])) {
        if (_ch.completed) {
          _restored[_ch.chunk_id] = { score: _ch.score ?? null, mode_used: _ch.mode_used ?? null };
        }
      }
      return {
        ...state,
        chunkList: action.payload.chunks,
        chunkIndex: action.payload.current_chunk_index,
        chunkProgress: { ...state.chunkProgress, ..._restored },
        conceptTitle: action.payload.section_title || state.conceptTitle,
        phase: "SELECTING_CHUNK",
        loading: false,
      };
    }

    case "RETURN_TO_PICKER":
      return {
        ...state,
        phase: "SELECTING_CHUNK",
        cards: [],
        currentCardIndex: 0,
        maxReachedIndex: 0,
        currentChunkId: null,
        nextChunkCards: null,
        nextChunkInFlight: false,
        loading: false,
        chunkEvalResult: null,
        chunkQuestions: [],
        cardAnswers: {},
      };

    case "CHUNK_CARDS_LOADED_NEW":
      return {
        ...state,
        cards: action.payload.cards,
        chunkQuestions: action.payload.questions ?? [],
        currentCardIndex: 0,
        maxReachedIndex: 0,
        chunkIndex: action.payload.chunk_index_after ?? state.chunkIndex,
        currentChunkId: action.payload.chunk_id ?? null,
        phase: "CARDS",
        loading: false,
        hasMoreConcepts: (action.payload.chunk_index_after ?? state.chunkIndex) < state.chunkList.length - 1,
        cardAnswers: {},
        chunkEvalResult: null,
      };

    case "NEXT_CHUNK_FETCH_STARTED":
      return { ...state, nextChunkInFlight: true };

    case "NEXT_CHUNK_CARDS_READY":
      return { ...state, nextChunkCards: action.payload, nextChunkInFlight: false };

    case "NEXT_CHUNK_FETCH_DONE":
      return { ...state, nextChunkInFlight: false };

    case "CHUNK_ADVANCE":
      if (!(state.nextChunkCards?.cards?.length > 0)) return state; // safety guard
      return {
        ...state,
        cards: state.nextChunkCards?.cards ?? [],
        chunkIndex: state.chunkIndex + 1,
        currentCardIndex: 0,
        maxReachedIndex: 0,
        currentChunkId: state.nextChunkCards?.chunk_id ?? state.currentChunkId,
        nextChunkCards: null,
        nextChunkInFlight: false,
        hasMoreConcepts: (state.chunkIndex + 1) < state.chunkList.length - 1,
      };

    case "SHOW_CHUNK_QUESTIONS":
      return { ...state, phase: "CHUNK_QUESTIONS", chunkEvalResult: null };

    case "CHUNK_EVAL_RESULT": {
      const { passed, all_study_complete, chunk_progress, next_mode, ...rest } = action.payload;
      const newMode = next_mode || state.currentChunkMode;
      let newState = {
        ...state,
        chunkEvalResult: { passed, all_study_complete, ...rest },
        loading: false,
        currentChunkMode: newMode,
        modeJustChanged: newMode !== state.currentChunkMode,
      };
      if (passed) {
        if (chunk_progress) {
          newState.chunkProgress = { ...state.chunkProgress, ...chunk_progress };
        }
        if (all_study_complete) {
          newState.allStudyComplete = true;
          if (state.session?.concept_id) {
            localStorage.removeItem(`ada_session_${state.session.student_id}_${state.session.concept_id}`);
          }
          newState.phase = "COMPLETED";
        }
        // If not all_study_complete, stay in CHUNK_QUESTIONS to show result; RETURN_TO_PICKER fires after 1.5s
      }
      return newState;
    }

    case "ADAPTIVE_CARD_ERROR":
      return {
        ...state,
        adaptiveCardLoading: false,
        currentCardIndex: state.cards.length > 0
          ? Math.min(state.currentCardIndex, state.cards.length - 1)
          : 0,
        idleTriggerCount: 0,
        motivationalNote: null,
        performanceVsBaseline: null,
      };
    case "SET_LOADING":
      return { ...state, loading: action.payload };
    case "CHUNK_COMPLETED": {
      const prevMode = state.currentChunkMode;
      const newMode = action.payload.next_mode || prevMode;
      return {
        ...state,
        chunkProgress: {
          ...state.chunkProgress,
          [action.payload.chunk_id]: {
            score: action.payload.score,
            mode_used: action.payload.next_mode,
          },
        },
        currentChunkMode: newMode,
        allStudyComplete: action.payload.all_study_complete ?? state.allStudyComplete,
        modeJustChanged: newMode !== prevMode,
      };
    }

    case "MODE_CHANGE_ACKNOWLEDGED":
      return { ...state, modeJustChanged: false };

    case "LANGUAGE_CHANGED":
      // Replace chunk headings by index from translated_headings, clear card cache
      return {
        ...state,
        chunkList: state.chunkList.map((chunk, i) => ({
          ...chunk,
          heading: action.payload.headings[i] ?? chunk.heading,
        })),
        cards: [],
        currentCardIndex: 0,
        maxReachedIndex: 0,
        cardAnswers: {},
      };

    case "CHUNK_ITEM_COMPLETE":
      return {
        ...state,
        chunkList: state.chunkList.map((c) =>
          c.chunk_id === action.payload.chunk_id
            ? { ...c, completed: true }
            : c
        ),
        allStudyComplete: action.payload.all_study_complete ?? state.allStudyComplete,
      };

    case "RESET":
      // Memory-only reset — does NOT clear localStorage.
      // Use SESSION_COMPLETED to clear localStorage on deliberate completion.
      return initialState;

    case "SESSION_COMPLETED":
      if (state.session?.concept_id) {
        localStorage.removeItem(`ada_session_${state.session.student_id}_${state.session.concept_id}`);
      }
      return initialState;
    case "ERROR":
      return { ...state, error: action.payload, loading: false, phase: state.phase === "LOADING" ? "SELECTING_CHUNK" : state.phase };
    case "CLEAR_ERROR":
      return { ...state, error: null };
    default:
      return state;
  }
}


export function SessionProvider({ children }) {
  const [state, dispatch] = useReducer(sessionReducer, initialState);
  const { student, refreshMastery } = useStudent();
  const { style } = useTheme();

  const friendlyError = (err) => {
    console.error("[AL] API error:", err.code, err.response?.status, err.message);
    if (err.code === "ECONNABORTED" || err.message?.includes("timeout")) {
      return i18n.t("error.timeout");
    }
    if (err.response?.status === 401) {
      return i18n.t("error.authFailed", "Authentication failed — check API key config.");
    }
    if (err.response?.status === 503) {
      return err.response?.data?.detail || i18n.t("error.serviceNotReady", "Service not ready — please wait a moment and try again.");
    }
    if (err.response?.status >= 400) {
      const detail = err.response?.data?.detail;
      const detailStr = Array.isArray(detail) ? detail.map(d => d.msg || JSON.stringify(d)).join("; ") : (typeof detail === "string" ? detail : null);
      return detailStr || `Server error (${err.response.status})`;
    }
    if (err.code === "ERR_NETWORK") {
      return i18n.t("error.network");
    }
    const detail = err.response?.data?.detail;
    return (Array.isArray(detail) ? detail.map(d => d.msg || JSON.stringify(d)).join("; ") : detail) || err.message;
  };

  const startLesson = useCallback(
    async (conceptId, lessonStyle, lessonInterests = []) => {
      if (!student) return;
      dispatch({ type: "START_LOADING" });
      try {
        const effectiveStyle = lessonStyle || style;
        const sessionRes = await startSession(student.id, conceptId, effectiveStyle, lessonInterests);
        dispatch({ type: "SESSION_CREATED", payload: sessionRes.data });

        // Check for chunk list — if the concept has chunks, use chunk flow
        const chunkListRes = await getChunkList(sessionRes.data.id);
        const chunkListData = chunkListRes?.data ?? {};
        if (chunkListData.chunks && chunkListData.chunks.length > 0) {
          // Chunk path: show subsection picker — student selects which chunk to start
          dispatch({ type: "CHUNK_LIST_LOADED", payload: chunkListData });
        } else {
          // GET /chunks returned an empty list — this should never happen now that ChromaDB
          // has been removed and every concept must go through the chunk pipeline.
          dispatch({
            type: "ERROR",
            payload: `No chunks found for session ${sessionRes.data.id}. ` +
              "The chunk pipeline may not have run for this concept. " +
              "Re-run the extraction pipeline and try again.",
          });
        }
        trackEvent("cards_loaded", { concept_id: conceptId });
      } catch (err) {
        trackEvent("lesson_error", {
          error_message: friendlyError(err),
          concept_id: conceptId,
        });
        dispatch({ type: "ERROR", payload: friendlyError(err) });
      }
    },
    [student, style]
  );

  const startChunk = useCallback(
    async (chunkId, chunkStyle, chunkInterests = []) => {
      if (!state.session?.id) return;
      dispatch({ type: "CHUNK_LOADING" });
      try {
        if (chunkStyle) {
          try {
            await switchStyle(state.session.id, chunkStyle);
          } catch (styleErr) {
            // 409 = session already past PRESENTING phase; non-blocking, card load continues
            console.error("[startChunk] switchStyle failed (non-blocking):", styleErr?.response?.status ?? styleErr);
          }
        }
        if (chunkInterests.length) await updateSessionInterests(state.session.id, chunkInterests);
        const res = await generateChunkCards(state.session.id, chunkId);
        if (!res?.cards?.length) {
          dispatch({ type: "ERROR", payload: i18n.t("learning.noCardsError") });
          return;
        }
        dispatch({
          type: "CHUNK_CARDS_LOADED_NEW",
          payload: {
            cards: res.cards,
            questions: res.questions ?? [],
            chunk_index_after: res.chunk_index,
            chunk_id: chunkId,
          },
        });
      } catch (err) {
        dispatch({ type: "ERROR", payload: friendlyError(err) });
      }
    },
    [state.session]
  );

  const goToNextCard = useCallback(
    async (signals) => {
      // If no session or no signals, just advance index
      if (!state.session || !signals) {
        dispatch({ type: "NEXT_CARD" });
        return;
      }

      // CASE A: second MCQ fail → recovery card via chunk-recovery-card endpoint
      if (signals?.wrongAttempts >= 2 && signals?.reExplainCardTitle) {
        const currentCard = state.cards[state.currentCardIndex];
        // Anti-loop: if current card is already a recovery card, just advance — no nested recovery
        if (currentCard?.is_recovery || currentCard?.card_type === "recovery") {
          dispatch({ type: "NEXT_CARD" });
          return;
        }
        // Record failed interaction so analytics capture it (0 XP for wrong answer)
        try {
          await recordCardInteraction(state.session.id, { ...signals, isCorrect: false });
        } catch (err) {
          console.error("[card] failed interaction record failed:", err);
        }
        const chunkMeta = state.chunkList?.find(c => c.chunk_id === state.currentChunkId);
        const isExercise = chunkMeta?.chunk_type === "exercise";
        dispatch({ type: "ADAPTIVE_CALL_STARTED" });
        try {
          const res = await generateChunkRecoveryCard(
            state.session.id,
            currentCard?.chunk_id,
            state.currentCardIndex,
            signals?.wrongAnswerText ? [signals.wrongAnswerText] : [],
            isExercise
          );
          const recoveryCard = res?.recovery_card ?? (res?.content || res?.title ? res : null);
          if (recoveryCard) {
            dispatch({ type: "INSERT_RECOVERY_CARD", payload: recoveryCard });
          }
          dispatch({ type: "NEXT_CARD" });   // advance past the failed card
          const xpData = res?.xp_awarded;
          if (xpData?.final_xp) {
            useAdaptiveStore.getState().awardXP(xpData.final_xp);
          }
        } catch (err) {
          console.error("[SessionContext] recovery card fetch failed:", err);
          dispatch({ type: "ADAPTIVE_CARD_ERROR" });
          dispatch({ type: "NEXT_CARD" });   // still advance so student is not stuck
        } finally {
          dispatch({ type: "ADAPTIVE_CALL_DONE" });
        }
        return;
      }

      // CASE D: mid-batch — record interaction and advance index
      try {
        const res = await recordCardInteraction(state.session.id, signals);
        // Award XP from backend gamification engine (replaces hardcoded awardXP(10))
        const xpData = res?.data?.xp_awarded;
        if (xpData?.final_xp) {
          useAdaptiveStore.getState().awardXP(xpData.final_xp);
        }
        // Update daily streak if returned
        if (xpData?.streak_info) {
          useAdaptiveStore.getState().setDailyStreak(xpData.streak_info);
        }
        // Handle new badges
        const newBadges = res?.data?.new_badges || [];
        if (newBadges.length) {
          newBadges.forEach((b) => useAdaptiveStore.getState().addBadge(b));
        }
      } catch (err) {
        console.error("[card] recordCardInteraction failed:", err);
      }

      dispatch({ type: "NEXT_CARD" });
    },
    [
      state.session,
      state.cards.length,
      state.currentCardIndex,
      state.adaptiveCallInFlight,
      state.chunkList,
      state.currentChunkId,
      state.currentChunkMode,
    ]
  );

  const goToPrevCard = useCallback(() => {
    dispatch({ type: "PREV_CARD" });
  }, []);

  const answerQuestion = useCallback((questionId, answer, correct) => {
    dispatch({
      type: "CARD_ANSWERED",
      payload: { questionId, answer, correct },
    });
  }, []);

  const sendAssistMessage = useCallback(
    async (message, trigger = "user") => {
      if (!state.session) return;
      if (trigger === "idle") {
        dispatch({ type: "IDLE_TRIGGERED" });
      }
      if (trigger === "user" && message) {
        dispatch({ type: "ASSIST_SENT", payload: message });
      }
      try {
        const res = await assistStudent(
          state.session.id,
          state.currentCardIndex,
          message,
          trigger,
        );
        dispatch({ type: "ASSIST_RESPONDED", payload: res.data.response });
      } catch (err) {
        dispatch({
          type: "ASSIST_RESPONDED",
          payload: i18n.t("error.assistFallback"),
        });
      }
    },
    [state.session, state.currentCardIndex]
  );

  // Finish cards → transition to Socratic chat for mastery
  const finishCards = useCallback(async (signals) => {
    if (!state.session) return;
    const correctCount = Object.values(state.cardAnswers).filter((a) => a.correct).length;
    trackEvent("cards_completed", {
      answers_correct: correctCount,
      answers_total: Object.keys(state.cardAnswers).length,
      concept_id: state.session?.concept_id,
      concept_title: state.conceptTitle,
    });
    try {
      if (signals) {
        const res = await recordCardInteraction(state.session.id, signals).catch((err) => console.error("[SessionContext] card interaction failed:", err));
          if (!res) {
            console.error("[SessionContext] card interaction response missing — skipping XP/badge processing");
            return;
          }
          // Award XP from backend response
          const xpData = res?.data?.xp_awarded;
          if (xpData?.final_xp) {
            useAdaptiveStore.getState().awardXP(xpData.final_xp);
          }
          if (res?.data?.new_badges?.length) {
            res.data.new_badges.forEach((b) => useAdaptiveStore.getState().addBadge(b));
          }
      }
      await completeCards(state.session.id);
    } catch (err) {
      console.error("[SessionContext] finishCards error:", err);
    }
    // If questions were generated for this chunk, show Q&A phase
    if (state.chunkQuestions.length > 0) {
      dispatch({ type: "SHOW_CHUNK_QUESTIONS" });
    } else {
      // No KC questions: exercise/info chunks auto-complete; teaching chunks degrade gracefully
      const chunkMeta = state.chunkList?.find(c => c.chunk_id === state.currentChunkId);
      const isTeaching = chunkMeta?.chunk_type === "teaching";
      if (isTeaching) {
        // Intentional console.error for monitoring — signals KC generation failure in backend
        console.error("[finishCards] teaching chunk has no KC questions — auto-completing as fallback");
      }
      if (state.currentChunkId) {
        try {
          const _answers = Object.values(state.cardAnswers);
          const _correct = _answers.filter(a => a.correct).length;
          const _total = _answers.length > 0 ? _answers.length : 1;
          const res = await completeChunk(state.session.id, {
            chunk_id: state.currentChunkId,
            correct: _correct,
            total: _total,
            mode_used: state.currentChunkMode || "NORMAL",
          });
          dispatch({ type: "CHUNK_COMPLETED", payload: res.data });
          if (res.data.next_mode) {
            useAdaptiveStore.getState().setMode(res.data.next_mode);
          }
        } catch (err) {
          console.error("[finishCards] auto-complete chunk failed:", err);
          dispatch({ type: "ERROR", payload: i18n.t("error.chunkCompleteFailed", "Failed to save your progress. Please try again.") });
        }
      }
      dispatch({ type: "RETURN_TO_PICKER" });
    }
  }, [state.session, state.cardAnswers, state.conceptTitle, state.chunkQuestions, state.currentChunkId, state.currentChunkMode]);

  const loadChunkCards = useCallback(async (chunkId) => {
    if (!state.session?.id) return;
    try {
      const response = await generateChunkCards(state.session.id, chunkId);
      dispatch({ type: "CHUNK_CARDS_LOADED", payload: response });
    } catch (err) {
      console.error("Failed to load chunk cards:", err);
      dispatch({ type: "ERROR", payload: friendlyError(err) });
    }
  }, [state.session?.id]);

  const goToNextChunk = useCallback(() => {
    dispatch({ type: "RETURN_TO_PICKER" });
  }, []);

  const submitChunkAnswers = useCallback(async (chunkId, questions, answers, modeUsed) => {
    if (!state.session) return;
    dispatch({ type: "TRANSITION_LOADING" });
    try {
      // Collect MCQ behavioral data from card phase
      const _mcqAnswers = Object.values(state.cardAnswers);
      const _mcqCorrect = _mcqAnswers.filter(a => a.correct).length;
      const _mcqTotal = _mcqAnswers.length;

      const res = await evaluateChunkAnswers(state.session.id, chunkId, {
        questions,
        answers,
        mode_used: modeUsed || "NORMAL",
        mcq_correct: _mcqCorrect,
        mcq_total: _mcqTotal,
      });
      dispatch({ type: "CHUNK_EVAL_RESULT", payload: res.data });
      // Handle new badges from chunk evaluation
      const evalBadges = res?.data?.new_badges || [];
      if (evalBadges.length) {
        evalBadges.forEach((b) => useAdaptiveStore.getState().addBadge(b));
      }
      // Award mastery XP if returned from backend
      const evalXp = res?.data?.xp_awarded;
      if (evalXp?.final_xp) {
        useAdaptiveStore.getState().awardXP(evalXp.final_xp);
      }
      if (res.data.passed) {
        refreshMastery();
        // Sync Zustand so AdaptiveModeIndicator reflects backend mode
        if (res.data.next_mode) {
          useAdaptiveStore.getState().setMode(res.data.next_mode);
        }
        // Only return to picker when concept is NOT complete
        // When all_study_complete=true, CHUNK_EVAL_RESULT already sets phase="COMPLETED"
        if (!res.data.all_study_complete) {
          setTimeout(() => dispatch({ type: "RETURN_TO_PICKER" }), 1500);
        }
      }
    } catch (err) {
      console.error("[SessionContext] submitChunkAnswers failed:", err);
      dispatch({ type: "ERROR", payload: friendlyError(err) });
    }
  }, [state.session, state.cardAnswers, refreshMastery]);

  const completeChunkAction = useCallback(async (chunkId, correct, total, modeUsed) => {
    if (!state.session?.id) return;
    try {
      const res = await completeChunk(state.session.id, {
        chunk_id: chunkId,
        correct,
        total,
        mode_used: modeUsed,
      });
      dispatch({ type: "CHUNK_COMPLETED", payload: res.data });
      return res.data;
    } catch (err) {
      console.error("[SessionContext] completeChunk failed:", err);
    }
  }, [state.session?.id]);

  const completeChunkItem = useCallback(async (chunkId) => {
    if (!state.session?.id) return;
    try {
      const res = await completeChunkItemAPI(state.session.id, chunkId);
      dispatch({ type: "CHUNK_ITEM_COMPLETE", payload: res.data });
      return res.data;
    } catch (err) {
      console.error("[SessionContext] completeChunkItem failed:", err);
    }
  }, [state.session?.id]);

  const reloadCurrentChunk = useCallback(async () => {
    if (!state.session?.id || !state.currentChunkId || state.phase !== "CARDS") return;
    dispatch({ type: "CHUNK_LOADING" });
    try {
      const res = await generateChunkCards(state.session.id, state.currentChunkId);
      if (res?.cards?.length) {
        dispatch({
          type: "CHUNK_CARDS_LOADED_NEW",
          payload: {
            cards: res.cards,
            questions: res.questions ?? [],
            chunk_index_after: res.chunk_index,
            chunk_id: state.currentChunkId,
          },
        });
      } else {
        dispatch({ type: "RETURN_TO_PICKER" });
      }
    } catch (err) {
      dispatch({ type: "ERROR", payload: friendlyError(err) });
    }
  }, [state.session?.id, state.currentChunkId, state.phase]);

  const reset = useCallback(() => {
    dispatch({ type: "RESET" });
  }, []);

  return (
    <SessionContext.Provider
      value={{
        ...state,
        dispatch,
        startLesson,
        startChunk,
        goToNextCard,
        goToPrevCard,
        answerQuestion,
        sendAssistMessage,
        finishCards,
        reset,
        loadChunkCards,
        goToNextChunk,
        completeChunkAction,
        completeChunkItem,
        submitChunkAnswers,
        reloadCurrentChunk,
        currentChunkIndex: state.currentChunkIndex,
        totalChunks: state.totalChunks,
        // Chunk navigation
        chunkList: state.chunkList,
        chunkIndex: state.chunkIndex,
        nextChunkInFlight: state.nextChunkInFlight,
        nextChunkCards: state.nextChunkCards,
        // Chunk progress
        chunkProgress: state.chunkProgress,
        currentChunkMode: state.currentChunkMode,
        allStudyComplete: state.allStudyComplete,
        modeJustChanged: state.modeJustChanged,
        // Per-chunk Q&A
        chunkQuestions: state.chunkQuestions,
        chunkEvalResult: state.chunkEvalResult,
      }}
    >
      {children}
    </SessionContext.Provider>
  );
}

export function useSession() {
  const context = useContext(SessionContext);
  if (!context) throw new Error("useSession must be used within SessionProvider");
  return context;
}
