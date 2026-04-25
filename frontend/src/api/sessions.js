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
  if (!conceptId) return "prealgebra";
  // New format: "prealgebra_1.1" — slug is everything before the trailing _<digits>.<digits>
  const newFormatMatch = conceptId.match(/^(.+)_\d+\.\d+$/);
  if (newFormatMatch) return newFormatMatch[1];
  // Old format: "PREALG.C1.S1..." — look up by first segment
  const code = conceptId.split(".")?.[0];
  return BOOK_CODE_TO_SLUG[code] ?? "prealgebra";
};

export const startSession = (studentId, conceptId) =>
  api.post("/api/v2/sessions", {
    student_id: studentId,
    concept_id: conceptId,
    book_slug: getBookSlugFromConceptId(conceptId),
  });

export const getSession = (sessionId) =>
  api.get(`/api/v2/sessions/${sessionId}`);

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
    difficulty:         signals.difficulty ?? null,
    is_correct:         signals.isCorrect ?? false,
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
      re_explain_card_title:   signals.reExplainCardTitle ?? null,
      wrong_question:          signals.wrongQuestion ?? null,
      wrong_answer_text:       signals.wrongAnswerText ?? null,
    },
    { timeout: COMPLETE_CARD_TIMEOUT }
  );

export const regenerateMCQ = (sessionId, body) =>
  api.post(`/api/v2/sessions/${sessionId}/regenerate-mcq`, body, { timeout: LLM_TIMEOUT });

// Generate all cards for a chunk
export async function generateChunkCards(sessionId, chunkId) {
  const { data } = await api.post(
    `/api/v2/sessions/${sessionId}/chunk-cards`,
    { chunk_id: chunkId },
    { timeout: CARDS_TIMEOUT }
  );
  return data; // ChunkCardsResponse: { cards, chunk_id, chunk_index, total_chunks, is_last_chunk }
}

// Get recovery card after 2 MCQ failures
export async function generateChunkRecoveryCard(sessionId, chunkId, cardIndex, wrongAnswers = [], isExercise = false) {
  const { data } = await api.post(
    `/api/v2/sessions/${sessionId}/chunk-recovery-card`,
    { chunk_id: chunkId, card_index: cardIndex, wrong_answers: wrongAnswers, is_exercise: isExercise },
    { timeout: LLM_TIMEOUT }
  );
  return data; // LessonCard
}

export const getChunkList = (sessionId) =>
  api.get(`/api/v2/sessions/${sessionId}/chunks`);

export const completeChunk = (sessionId, payload) =>
  api.post(`/api/v2/sessions/${sessionId}/complete-chunk`, payload);

export const completeChunkItem = (sessionId, chunkId) =>
  api.post(`/api/v2/sessions/${sessionId}/chunks/${chunkId}/complete`, {});

export const evaluateChunkAnswers = (sessionId, chunkId, data) =>
  api.post(`/api/v2/sessions/${sessionId}/chunks/${chunkId}/evaluate`, data, { timeout: 60000 });

