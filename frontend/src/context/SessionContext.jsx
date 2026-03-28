import { createContext, useContext, useReducer, useCallback } from "react";
import i18n from "i18next";
import {
  startSession,
  getCards,
  assistStudent,
  completeCards,
  beginCheck,
  sendResponse,
  completeCardAndGetNext,
  completeSection,
  recordCardInteraction,
  loadRemediationCards as loadRemediationCardsAPI,
  beginRecheck as beginRecheckAPI,
  getNextSectionCards,
  fetchNextAdaptiveCard,
} from "../api/sessions";
import { useStudent } from "./StudentContext";
import { useTheme } from "./ThemeContext";
import { trackEvent } from "../utils/analytics";
import { useAdaptiveStore } from "../store/adaptiveStore";

const SessionContext = createContext();

const initialState = {
  phase: "IDLE",
  session: null,
  conceptTitle: "",
  // Card-based learning
  cards: [],
  currentCardIndex: 0,
  maxReachedIndex: 0,
  cardAnswers: {},
  totalQuestions: 0,
  // AI assistant
  assistMessages: [],
  assistLoading: false,
  // Socratic chat (mastery assessment)
  messages: [],
  checkLoading: false,
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
  difficultyBias: null,
  // Remediation / re-check flow
  socraticAttempt: 0,
  remediationNeeded: false,
  checkScore: null,
  checkPassed: null,
  conceptLocked: false,
  bestScore: null,
  // Rolling adaptive replace
  adaptiveCallInFlight: false,
  // Rolling section generation
  hasMoreConcepts: true,
  conceptsTotal: 0,
  conceptsCoveredCount: 0,
  rollingCallInFlight: false,
  // Per-card adaptive generation
  nextCardInFlight: false,
};

// Valid phases: IDLE, LOADING, CARDS, CHECKING, COMPLETED,
//               REMEDIATING, RECHECKING, REMEDIATING_2, RECHECKING_2, ATTEMPTS_EXHAUSTED

function sessionReducer(state, action) {
  switch (action.type) {
    case "START_LOADING":
      return { ...initialState, phase: "LOADING", loading: true };
    case "TRANSITION_LOADING":
      return { ...state, loading: true };
    case "SESSION_CREATED":
      return { ...state, session: action.payload };
    case "CARDS_LOADED":
      return {
        ...state,
        cards: action.payload.cards,
        conceptTitle: action.payload.concept_title,
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

    case "ROLLING_CALL_STARTED":
      return { ...state, rollingCallInFlight: true };

    case "ROLLING_CALL_DONE":
      return { ...state, rollingCallInFlight: false };

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

    case "APPEND_CARDS":
      return {
        ...state,
        cards: [...state.cards, ...action.payload.cards],
        hasMoreConcepts: action.payload.has_more_concepts,
        conceptsTotal: action.payload.concepts_total,
        conceptsCoveredCount: action.payload.concepts_covered_count,
        learningProfileSummary: action.payload.learning_profile_summary ?? null,
        rollingCallInFlight: false,
        adaptiveCallInFlight: false,
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

    case "SET_DIFFICULTY_BIAS":
      return { ...state, difficultyBias: action.payload };
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
    // Transition: cards done → Socratic chat
    case "CHECKING_STARTED":
      return {
        ...state,
        phase: "CHECKING",
        messages: [{ role: "assistant", content: action.payload.response, image: action.payload.image ?? null }],
        loading: false,
      };
    case "ANSWER_SENT":
      return {
        ...state,
        messages: [
          ...state.messages,
          { role: "user", content: action.payload },
        ],
        checkLoading: true,
      };
    case "CHECK_RESPONDED": {
      const base = {
        ...state,
        messages: [
          ...state.messages,
          { role: "assistant", content: action.payload.response, image: action.payload.image ?? null },
        ],
        checkLoading: false,
      };
      if (!action.payload.check_complete) return base;

      const { mastered, remediation_needed, score, attempt, locked, best_score } = action.payload;

      // Mastered on this attempt
      if (mastered) {
        return {
          ...base,
          phase: "COMPLETED",
          score,
          mastered: true,
          checkPassed: true,
          checkScore: score,
          bestScore: best_score ?? score,
        };
      }

      // Remediation needed (still have attempts left)
      if (remediation_needed) {
        const nextRemPhase = attempt <= 1 ? "REMEDIATING" : "REMEDIATING_2";
        return {
          ...base,
          phase: nextRemPhase,
          remediationNeeded: true,
          checkScore: score,
          checkPassed: false,
          socraticAttempt: attempt ?? state.socraticAttempt,
          bestScore: best_score ?? score,
        };
      }

      // All attempts exhausted (locked === false means concept NOT hard-locked, but session done)
      return {
        ...base,
        phase: "ATTEMPTS_EXHAUSTED",
        score,
        mastered: false,
        checkPassed: false,
        checkScore: score,
        bestScore: best_score ?? score,
        conceptLocked: locked ?? false,
      };
    }
    case "SOCRATIC_FAILED": {
      const nextPhase = action.payload.attempt <= 1 ? "REMEDIATING" : "REMEDIATING_2";
      return {
        ...state,
        phase: nextPhase,
        remediationNeeded: true,
        checkScore: action.payload.score,
        checkPassed: false,
        socraticAttempt: action.payload.attempt,
      };
    }
    case "ATTEMPTS_EXHAUSTED":
      return {
        ...state,
        phase: "ATTEMPTS_EXHAUSTED",
        score: action.payload.score,
        mastered: false,
        checkPassed: false,
        checkScore: action.payload.score,
        bestScore: action.payload.bestScore,
      };
    case "SET_LOADING":
      return { ...state, loading: action.payload };
    case "REMEDIATION_CARDS_LOADED": {
      // Determine which remediation phase we are entering
      const remPhase = state.socraticAttempt <= 1 ? "REMEDIATING" : "REMEDIATING_2";
      return {
        ...state,
        cards: action.payload,
        currentCardIndex: 0,
        phase: remPhase,
        loading: false,
        remediationNeeded: false,
      };
    }
    case "RECHECK_STARTED": {
      const recheckPhase = action.payload.phase || (state.socraticAttempt <= 1 ? "RECHECKING" : "RECHECKING_2");
      return {
        ...state,
        phase: recheckPhase,
        messages: [{ role: "assistant", content: action.payload.response }],
        loading: false,
      };
    }
    case "RESET":
      return initialState;
    case "ERROR":
      return { ...state, error: action.payload, loading: false };
    default:
      return state;
  }
}


export function SessionProvider({ children }) {
  const [state, dispatch] = useReducer(sessionReducer, initialState);
  const { student, refreshMastery } = useStudent();
  const { style } = useTheme();

  const friendlyError = (err) => {
    console.error("[ADA] API error:", err.code, err.response?.status, err.message);
    if (err.code === "ECONNABORTED" || err.message?.includes("timeout")) {
      return i18n.t("error.timeout");
    }
    if (err.response?.status === 401) {
      return "Authentication failed — check API key config.";
    }
    if (err.response?.status >= 400) {
      return err.response?.data?.detail || `Server error (${err.response.status})`;
    }
    if (err.code === "ERR_NETWORK") {
      return i18n.t("error.network");
    }
    return err.response?.data?.detail || err.message;
  };

  const startLesson = useCallback(
    async (conceptId, lessonStyle, lessonInterests = []) => {
      if (!student) return;
      dispatch({ type: "START_LOADING" });
      try {
        const effectiveStyle = lessonStyle || style;
        const sessionRes = await startSession(student.id, conceptId, effectiveStyle, lessonInterests);
        dispatch({ type: "SESSION_CREATED", payload: sessionRes.data });
        const cardsRes = await getCards(sessionRes.data.id);
        dispatch({ type: "CARDS_LOADED", payload: cardsRes.data });
        trackEvent("cards_loaded", {
          card_count: cardsRes.data.cards?.length || 0,
          question_count: cardsRes.data.total_questions || 0,
          concept_id: cardsRes.data.concept_id,
          concept_title: cardsRes.data.concept_title,
        });
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

  const goToNextCard = useCallback(
    async (signals) => {
      // If no session or no signals, just advance index
      if (!state.session || !signals) {
        dispatch({ type: "NEXT_CARD" });
        return;
      }

      const nearEnd = state.currentCardIndex >= state.cards.length - 2;
      let rollingJustStarted = false;

      // CASE A: both MCQs wrong → recovery card via completeCardAndGetNext
      if (signals?.wrongAttempts >= 2 && signals?.reExplainCardTitle) {
        dispatch({ type: "ADAPTIVE_CALL_STARTED" });
        try {
          const res = await completeCardAndGetNext(state.session.id, signals);
          // Only replace if backend returned an adapted card (field is absent in current schema)
          if (res.data?.card) {
            dispatch({ type: "REPLACE_UPCOMING_CARD", payload: res.data });
          }
          if (res.data?.recovery_card) {
            dispatch({ type: "INSERT_RECOVERY_CARD", payload: res.data.recovery_card });
          }
          dispatch({ type: "NEXT_CARD" });   // advance past the failed card
          useAdaptiveStore.getState().updateMode(res.data.learning_profile_summary);
          useAdaptiveStore.getState().awardXP(5);
        } catch (err) {
          console.error("[SessionContext] adaptive card fetch failed:", err);
          dispatch({ type: "ADAPTIVE_CARD_ERROR" });
          dispatch({ type: "NEXT_CARD" });   // still advance so student is not stuck
        } finally {
          dispatch({ type: "ADAPTIVE_CALL_DONE" });
        }
        return;
      }

      // CASE B: near end of batch AND more sections remain → pre-fetch next sub-section
      if (nearEnd && state.hasMoreConcepts && !state.rollingCallInFlight) {
        rollingJustStarted = true;
        dispatch({ type: "ROLLING_CALL_STARTED" });
        getNextSectionCards(state.session.id, {
          card_index: state.currentCardIndex,
          time_on_card_sec: signals?.timeOnCardSec ?? 0,
          wrong_attempts: signals?.wrongAttempts ?? 0,
          hints_used: signals?.hintsUsed ?? 0,
          idle_triggers: signals?.idleTriggers ?? 0,
        }).then(res => {
          dispatch({ type: "APPEND_CARDS", payload: res.data });
          if (res.data?.learning_profile_summary) {
            useAdaptiveStore.getState().updateMode(res.data.learning_profile_summary);
          }
        }).catch(err => {
          console.error("[rolling] failed to fetch next section:", err);
          dispatch({ type: "ROLLING_CALL_DONE" });
        });
        // Fall through — also advance the card index below (pre-fetch is async)
      }

      // CASE D: mid-batch — record interaction and advance index
      try {
        await recordCardInteraction(state.session.id, signals);
      } catch (err) {
        console.error("[card] recordCardInteraction failed:", err);
      }

      // Fire per-card adaptive fetch in background before advancing the index
      // so the new card lands at exactly currentCardIndex + 1 when it arrives.
      // Skip if rolling-section fetch was just triggered this invocation (mutually exclusive).
      if (!state.nextCardInFlight && state.hasMoreConcepts && !state.rollingCallInFlight && !rollingJustStarted) {
        dispatch({ type: "NEXT_CARD_FETCH_STARTED" });
        fetchNextAdaptiveCard(state.session.id, {
          card_index:       state.currentCardIndex,
          time_on_card_sec: signals?.timeOnCardSec ?? 30,
          wrong_attempts:   signals?.wrongAttempts ?? 0,
          hints_used:       signals?.hintsUsed ?? 0,
          idle_triggers:    signals?.idleTriggers ?? 0,
        }).then((res) => {
          if (res.data.card) {
            dispatch({ type: "APPEND_NEXT_CARD", payload: res.data });
          } else {
            // Queue exhausted — no new card, just clear the in-flight flag
            dispatch({ type: "NEXT_CARD_FETCH_DONE" });
          }
          if (!res.data.has_more_concepts) {
            dispatch({ type: "NEXT_CARD_FETCH_DONE" });
          }
          if (res.data?.learning_profile_summary) {
            useAdaptiveStore.getState().updateMode(res.data.learning_profile_summary);
          }
        }).catch((err) => {
          console.error("[per-card] next-card fetch failed:", err);
          dispatch({ type: "NEXT_CARD_FETCH_DONE" });
        });
      }

      dispatch({ type: "NEXT_CARD" });
    },
    [
      state.session,
      state.cards.length,
      state.currentCardIndex,
      state.adaptiveCallInFlight,
      state.hasMoreConcepts,
      state.rollingCallInFlight,
      state.nextCardInFlight,
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
    dispatch({ type: "TRANSITION_LOADING" });
    const correctCount = Object.values(state.cardAnswers).filter((a) => a.correct).length;
    trackEvent("cards_completed", {
      answers_correct: correctCount,
      answers_total: Object.keys(state.cardAnswers).length,
      concept_id: state.session?.concept_id,
      concept_title: state.conceptTitle,
    });
    try {
      // 0. Save the last card's interaction (not recorded via goToNextCard)
      if (signals) {
        await recordCardInteraction(state.session.id, signals).catch((err) => console.error("[SessionContext] card interaction failed:", err));
      }
      // 1. Complete cards (phase → CARDS_DONE)
      await completeCards(state.session.id);
      // 2. Begin Socratic check (phase → CHECKING)
      const checkRes = await beginCheck(state.session.id);
      dispatch({ type: "CHECKING_STARTED", payload: checkRes.data });
    } catch (err) {
      dispatch({ type: "ERROR", payload: friendlyError(err) });
    }
  }, [state.session, state.cardAnswers, state.conceptTitle]);

  // Send answer during Socratic chat (CHECKING or RECHECKING/RECHECKING_2)
  const sendAnswer = useCallback(
    async (message, engagementSignal = null) => {
      if (!state.session) return;
      dispatch({ type: "ANSWER_SENT", payload: message });
      try {
        const res = await sendResponse(state.session.id, message, engagementSignal);
        dispatch({ type: "CHECK_RESPONDED", payload: res.data });
        if (res.data.check_complete) {
          trackEvent("lesson_completed", {
            score: res.data.score,
            mastered: res.data.mastered,
            passed: res.data.passed,
            remediation_needed: res.data.remediation_needed,
            attempt: res.data.attempt,
            concept_id: state.session?.concept_id,
            concept_title: state.conceptTitle,
          });
          if (res.data.mastered || res.data.passed) {
            trackEvent("mastered", {
              score: res.data.score,
              concept_id: state.session?.concept_id,
              concept_title: state.conceptTitle,
            });
            const xpAwarded = res.data.xp_awarded ?? 50;
            useAdaptiveStore.getState().awardXP(xpAwarded);
          }
          await refreshMastery();
        }
      } catch (err) {
        dispatch({
          type: "CHECK_RESPONDED",
          payload: {
            response: i18n.t("error.checkFallback"),
            check_complete: false,
          },
        });
      }
    },
    [state.session, state.conceptTitle, refreshMastery]
  );

  // Load remediation cards after Socratic check failure
  const loadRemediationCards = useCallback(async (sessionId) => {
    dispatch({ type: "SET_LOADING", payload: true });
    try {
      const res = await loadRemediationCardsAPI(sessionId);
      dispatch({ type: "REMEDIATION_CARDS_LOADED", payload: res.data.cards });
    } catch (err) {
      dispatch({ type: "ERROR", payload: friendlyError(err) });
    }
  }, []);

  // Begin re-check Socratic session after remediation cards
  const startRecheck = useCallback(async (sessionId) => {
    dispatch({ type: "SET_LOADING", payload: true });
    try {
      const res = await beginRecheckAPI(sessionId);
      dispatch({
        type: "RECHECK_STARTED",
        payload: { response: res.data.response, phase: res.data.phase },
      });
    } catch (err) {
      dispatch({ type: "ERROR", payload: friendlyError(err) });
    }
  }, []);

  const reset = useCallback(() => {
    dispatch({ type: "RESET" });
  }, []);

  const setDifficultyBias = useCallback((bias) => {
    dispatch({ type: "SET_DIFFICULTY_BIAS", payload: bias });
  }, []);

  return (
    <SessionContext.Provider
      value={{
        ...state,
        startLesson,
        goToNextCard,
        goToPrevCard,
        answerQuestion,
        sendAssistMessage,
        finishCards,
        sendAnswer,
        loadRemediationCards,
        startRecheck,
        reset,
        setDifficultyBias,
        rollingCallInFlight: state.rollingCallInFlight,
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
