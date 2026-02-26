import { createContext, useContext, useReducer, useCallback } from "react";
import i18n from "i18next";
import {
  startSession,
  getCards,
  assistStudent,
  completeCards,
  beginCheck,
  sendResponse,
} from "../api/sessions";
import { useStudent } from "./StudentContext";
import { useTheme } from "./ThemeContext";
import { trackEvent } from "../utils/analytics";

const SessionContext = createContext();

const initialState = {
  phase: "IDLE",
  session: null,
  conceptTitle: "",
  // Card-based learning
  cards: [],
  currentCardIndex: 0,
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
};

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
      };
    case "NEXT_CARD":
      return {
        ...state,
        currentCardIndex: Math.min(state.currentCardIndex + 1, state.cards.length - 1),
      };
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
    // Transition: cards done → Socratic chat
    case "CHECKING_STARTED":
      return {
        ...state,
        phase: "CHECKING",
        messages: [{ role: "assistant", content: action.payload }],
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
    case "CHECK_RESPONDED":
      return {
        ...state,
        messages: [
          ...state.messages,
          { role: "assistant", content: action.payload.response },
        ],
        checkLoading: false,
        ...(action.payload.check_complete
          ? {
              phase: "COMPLETED",
              score: action.payload.score,
              mastered: action.payload.mastered,
            }
          : {}),
      };
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
    if (err.code === "ECONNABORTED" || err.message?.includes("timeout")) {
      return i18n.t("error.timeout");
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

  const goToNextCard = useCallback(() => {
    dispatch({ type: "NEXT_CARD" });
  }, []);

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
  const finishCards = useCallback(async () => {
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
      // 1. Complete cards (phase → CARDS_DONE)
      await completeCards(state.session.id);
      // 2. Begin Socratic check (phase → CHECKING)
      const checkRes = await beginCheck(state.session.id);
      dispatch({ type: "CHECKING_STARTED", payload: checkRes.data.response });
    } catch (err) {
      dispatch({ type: "ERROR", payload: friendlyError(err) });
    }
  }, [state.session, state.cardAnswers, state.conceptTitle]);

  // Send answer during Socratic chat
  const sendAnswer = useCallback(
    async (message) => {
      if (!state.session) return;
      dispatch({ type: "ANSWER_SENT", payload: message });
      try {
        const res = await sendResponse(state.session.id, message);
        dispatch({ type: "CHECK_RESPONDED", payload: res.data });
        if (res.data.check_complete) {
          trackEvent("lesson_completed", {
            score: res.data.score,
            mastered: res.data.mastered,
            concept_id: state.session?.concept_id,
            concept_title: state.conceptTitle,
          });
          if (res.data.mastered) {
            trackEvent("mastered", {
              score: res.data.score,
              concept_id: state.session?.concept_id,
              concept_title: state.conceptTitle,
            });
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

  const reset = useCallback(() => {
    dispatch({ type: "RESET" });
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
        reset,
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
