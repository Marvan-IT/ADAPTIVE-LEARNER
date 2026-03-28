import api from "./client";

// LLM-dependent calls need longer timeouts (reasoning models like DeepSeek R1 are slow)
const LLM_TIMEOUT = 180_000; // 3 minutes
const CARDS_TIMEOUT = 300_000; // 5 minutes (generates multiple cards + questions)

const BOOK_CODE_TO_SLUG = {
  PREALG: "prealgebra",
  ELEMALG: "elementary_algebra",
  INTERALG: "intermediate_algebra",
  COLALG: "college_algebra",
  COLALGCRQ: "college_algebra_coreq",
  ALGTRIG: "algebra_trigonometry",
  PRECALC: "precalculus",
  CALC1: "calculus_1",
  CALC2: "calculus_2",
  CALC3: "calculus_3",
  INSTATS: "intro_statistics",
  STATS: "statistics",
  BUSTATS: "business_statistics",
  CONTMATH: "contemporary_math",
  PDS: "principles_data_science",
};

export const getBookSlugFromConceptId = (conceptId) => {
  const code = conceptId?.split(".")?.[0];
  return BOOK_CODE_TO_SLUG[code] ?? "prealgebra";
};

export const startSession = (studentId, conceptId, style = "default", lessonInterests = []) =>
  api.post("/api/v2/sessions", {
    student_id: studentId,
    concept_id: conceptId,
    style,
    lesson_interests: lessonInterests.length > 0 ? lessonInterests : [],
    book_slug: getBookSlugFromConceptId(conceptId),
  });

export const getPresentation = (sessionId) =>
  api.post(`/api/v2/sessions/${sessionId}/present`, {}, { timeout: LLM_TIMEOUT });

export const beginCheck = (sessionId) =>
  api.post(`/api/v2/sessions/${sessionId}/check`, {}, { timeout: LLM_TIMEOUT });

export const sendResponse = (sessionId, message, engagementSignal = null) =>
  api.post(
    `/api/v2/sessions/${sessionId}/respond`,
    { message, engagement_signal: engagementSignal },
    { timeout: LLM_TIMEOUT }
  );

export const completeSection = (sessionId, conceptId, stateScore = 2.0) =>
  api.post(`/api/v2/sessions/${sessionId}/section-complete`, {
    concept_id: conceptId,
    state_score: stateScore,
  });

export const switchStyle = (sessionId, style) =>
  api.put(`/api/v2/sessions/${sessionId}/style`, { style }, { timeout: LLM_TIMEOUT });

export const getSession = (sessionId) =>
  api.get(`/api/v2/sessions/${sessionId}`);

// Card-based learning (longest timeout — AI generates multiple cards + questions)
export const getCards = (sessionId) =>
  api.post(`/api/v2/sessions/${sessionId}/cards`, {}, { timeout: CARDS_TIMEOUT });

export const assistStudent = (sessionId, cardIndex, message, trigger = "user") =>
  api.post(`/api/v2/sessions/${sessionId}/assist`, {
    card_index: cardIndex,
    message,
    trigger,
  }, { timeout: LLM_TIMEOUT });

export const completeCards = (sessionId) =>
  api.post(`/api/v2/sessions/${sessionId}/complete-cards`);

export const recordCardInteraction = (sessionId, signals) =>
  api.post(`/api/v2/sessions/${sessionId}/record-interaction`, {
    card_index:         signals.cardIndex,
    time_on_card_sec:   signals.timeOnCardSec,
    wrong_attempts:     signals.wrongAttempts,
    hints_used:         signals.hintsUsed,
    idle_triggers:      signals.idleTriggers,
    adaptation_applied: signals.adaptationApplied ?? null,
  });

const COMPLETE_CARD_TIMEOUT = 30_000;

export const completeCardAndGetNext = (sessionId, signals) =>
  api.post(
    `/api/v2/sessions/${sessionId}/complete-card`,
    {
      card_index:              signals.cardIndex,
      time_on_card_sec:        signals.timeOnCardSec,
      wrong_attempts:          signals.wrongAttempts,
      selected_wrong_option:   signals.selectedWrongOption ?? null,
      hints_used:              signals.hintsUsed,
      idle_triggers:           signals.idleTriggers,
      difficulty_bias:         signals.difficultyBias ?? null,
      re_explain_card_title:   signals.reExplainCardTitle ?? null,
      wrong_question:          signals.wrongQuestion ?? null,
      wrong_answer_text:       signals.wrongAnswerText ?? null,
    },
    { timeout: COMPLETE_CARD_TIMEOUT }
  );

export const updateSessionInterests = (sessionId, interests) =>
  api.put(`/api/v2/sessions/${sessionId}/interests`, { interests });

export const loadRemediationCards = (sessionId) =>
  api.post(`/api/v2/sessions/${sessionId}/remediation-cards`, {}, { timeout: CARDS_TIMEOUT });

export const beginRecheck = (sessionId) =>
  api.post(`/api/v2/sessions/${sessionId}/recheck`, {}, { timeout: LLM_TIMEOUT });

export const regenerateMCQ = (sessionId, body) =>
  api.post(`/api/v2/sessions/${sessionId}/regenerate-mcq`, body, { timeout: LLM_TIMEOUT });

export const getNextSectionCards = (sessionId, signals) =>
  api.post(`/api/v2/sessions/${sessionId}/next-section-cards`, signals || {}, { timeout: 45000 });

export const fetchNextAdaptiveCard = (sessionId, payload) =>
  api.post(`/api/v2/sessions/${sessionId}/next-card`, payload, { timeout: 45000 });

export const getBooks = async () => {
  const res = await api.get("/api/v2/books");
  return res.data;
};

export const getSpacedReviews = async (sessionId) => {
  const res = await api.get(`/api/v2/sessions/${sessionId}/spaced-reviews`);
  return res.data;
};

export const completeSpacedReview = async (sessionId, reviewId, score) => {
  const res = await api.post(
    `/api/v2/sessions/${sessionId}/spaced-reviews/${reviewId}/complete`,
    { score }
  );
  return res.data;
};
