/**
 * Shared E2E helpers for ADA Playwright test suite.
 *
 * Reads API_SECRET_KEY from ../../backend/.env (relative to this file's location
 * at frontend/e2e/helpers.js).
 */

import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

// ---------------------------------------------------------------------------
// API key loading
// ---------------------------------------------------------------------------

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

/**
 * Reads API_SECRET_KEY from the backend .env file.
 * Returns empty string if the file cannot be read.
 */
export function loadApiKey() {
  try {
    const envPath = resolve(__dirname, '../../backend/.env');
    const raw = readFileSync(envPath, 'utf-8');
    for (const line of raw.split('\n')) {
      const trimmed = line.trim();
      if (trimmed.startsWith('API_SECRET_KEY=')) {
        return trimmed.slice('API_SECRET_KEY='.length).trim();
      }
    }
  } catch {
    // File not found or unreadable — tests will fail with 401 but won't crash at import time
  }
  return '';
}

const API_BASE = 'http://localhost:8891';
const API_KEY = loadApiKey();

const defaultHeaders = {
  'Content-Type': 'application/json',
  'X-API-Key': API_KEY,
};

// ---------------------------------------------------------------------------
// Concept IDs used across spec files
// ---------------------------------------------------------------------------

export const CONCEPT_C1S1 = 'PREALG.C1.S1.INTRODUCTION_TO_WHOLE_NUMBERS';
export const CONCEPT_C1S2 = 'PREALG.C1.S2.ADD_WHOLE_NUMBERS';
export const CONCEPT_C1S3 = 'PREALG.C1.S3.SUBTRACT_WHOLE_NUMBERS';

// ---------------------------------------------------------------------------
// REST helpers — called from Node context (beforeAll, test body), NOT the browser
// ---------------------------------------------------------------------------

/**
 * Creates a student via the API and returns the student.id.
 * @param {string} name
 * @param {object} opts  { interests?, preferred_style?, preferred_language? }
 */
export async function createStudent(name, opts = {}) {
  const student = await createStudentFull(name, opts);
  return student.id;
}

/**
 * Creates a student via the API and returns the full student object.
 */
export async function createStudentFull(name, opts = {}) {
  const body = {
    display_name: name,
    interests: opts.interests ?? [],
    preferred_style: opts.preferred_style ?? 'default',
    preferred_language: opts.preferred_language ?? 'en',
  };
  const res = await fetch(`${API_BASE}/api/v2/students`, {
    method: 'POST',
    headers: defaultHeaders,
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(`createStudent failed: ${res.status} ${await res.text()}`);
  }
  return res.json();
}

/**
 * Creates a session for a student + concept via the API.
 * Returns the full session object.
 */
export async function createSession(studentId, conceptId) {
  const res = await fetch(`${API_BASE}/api/v2/sessions`, {
    method: 'POST',
    headers: defaultHeaders,
    body: JSON.stringify({ student_id: studentId, concept_id: conceptId }),
  });
  if (!res.ok) {
    throw new Error(`createSession failed: ${res.status} ${await res.text()}`);
  }
  return res.json();
}

/**
 * Fetches generated cards for a session.
 * Returns the full cards response { cards, concept_title, ... }.
 */
export async function fetchCards(sessionId) {
  const res = await fetch(`${API_BASE}/api/v2/sessions/${sessionId}/cards`, {
    method: 'POST',
    headers: defaultHeaders,
  });
  if (!res.ok) {
    throw new Error(`fetchCards failed: ${res.status} ${await res.text()}`);
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Playwright page helpers
// ---------------------------------------------------------------------------

/**
 * Sets the student ID in localStorage, waits for StudentContext to fully load
 * the student from the API, then navigates to /learn/{conceptId} using
 * React Router's in-app navigation (pushState) — NOT a full browser reload.
 *
 * Critical: startLesson() in SessionContext has `if (!student) return`.
 * If we do a full page.goto('/learn/...'), StudentContext reloads async and
 * student is null when LearningPage fires its useEffect → lesson never starts.
 * By using pushState, the already-loaded StudentContext (with student set) is
 * preserved and the LearningPage gets a non-null student immediately.
 */
export async function navigateToLearn(page, studentId, conceptId) {
  // 1. Load the app root.
  await page.goto('/');

  // 2. Set the student ID in localStorage BEFORE the app finishes mounting.
  //    The StudentContext reads localStorage on mount via useEffect.
  await page.evaluate((id) => {
    localStorage.setItem('ada_student_id', id);
  }, studentId);

  // 3. Reload so StudentContext picks up the new localStorage value and calls getStudent().
  await page.reload({ waitUntil: 'domcontentloaded' });

  // 4. Wait for the student's display name to appear on the WelcomePage.
  //    WelcomePage renders student.display_name when student is loaded.
  //    This confirms StudentContext.student !== null before we navigate.
  await page.waitForFunction(
    () => {
      const text = document.body.innerText || '';
      // WelcomePage shows the student name when loaded; also accepts if we see
      // the concept map or any substantial content (in case of fast navigation).
      return text.length > 80 &&
        !text.toLowerCase().includes('loading') &&
        !document.querySelector('[animation*="spin"]');
    },
    { timeout: 30_000 }
  );

  // Brief pause to ensure React has finished rendering the student in context.
  await page.waitForTimeout(300);

  // 5. Navigate using React Router's in-app navigation (pushState + popstate).
  //    This avoids a full page reload, so StudentContext keeps the loaded student.
  const encodedId = encodeURIComponent(conceptId);
  await page.evaluate((path) => {
    window.history.pushState({}, '', path);
    // Dispatch popstate so React Router (BrowserRouter) picks up the new URL.
    window.dispatchEvent(new PopStateEvent('popstate', { state: null }));
  }, `/learn/${encodedId}`);

  // 6. Wait for LearningPage to mount and trigger card loading.
  //    The loading text "ADA is crafting..." appears while cards load.
  await page.waitForFunction(
    () => {
      const text = document.body.innerText || '';
      // Either crafting (cards loading) or markdown-content (cards loaded) — both mean we're on the learning page
      return text.toLowerCase().includes('crafting') || !!document.querySelector('.markdown-content');
    },
    { timeout: 30_000 }
  );
}

/**
 * Waits up to 90 seconds for cards to fully load.
 * Cards are considered loaded when:
 *   - The "crafting" loading text is gone, AND
 *   - At least one .rounded-full progress dot is visible
 */
export async function waitForCards(page, timeoutMs = 180_000) {
  // Wait for actual card content to appear.
  // .markdown-content is ONLY rendered by CardLearningView (real cards), NOT by the
  // loading skeleton — so this selector definitively means cards are ready.
  await page.waitForSelector('.markdown-content', { timeout: timeoutMs });

  // Brief stabilisation pause so React finishes painting card content
  await page.waitForTimeout(400);
}

/**
 * Fetches cards for the given session via the API and returns the correct_index
 * for the card at cardIndex. Returns null if the card has no question.
 *
 * @param {string} sessionId
 * @param {number} cardIndex
 */
export async function getCorrectOptionIndex(sessionId, cardIndex) {
  try {
    const data = await fetchCards(sessionId);
    const card = data.cards?.[cardIndex];
    if (!card) return null;
    // New schema: card.question.correct_index
    if (card.question?.correct_index != null) return card.question.correct_index;
    // Old schema: card.quick_check.correct_index
    if (card.quick_check?.correct_index != null) return card.quick_check.correct_index;
    // Old schema: card.questions[]
    if (card.questions?.length > 0) return card.questions[0].correct_index ?? null;
    return null;
  } catch {
    return null;
  }
}

/**
 * Clicks the correct MCQ option on the current card using the API to determine
 * which option index is correct. Returns true if an answer was clicked.
 *
 * @param {import('@playwright/test').Page} page
 * @param {string} sessionId   Session ID returned by the API
 * @param {number} cardIndex   Zero-based card index
 */
export async function answerMCQCorrectly(page, sessionId, cardIndex) {
  const correctIdx = await getCorrectOptionIndex(sessionId, cardIndex);
  if (correctIdx == null) return false;

  // MCQ options are pill-shaped buttons with a circular letter badge (A, B, C, D).
  // The label text inside the badge is the letter (A=0, B=1, C=2, D=3).
  const letter = String.fromCharCode(65 + correctIdx); // 0→A, 1→B, …

  // Find the MCQ option buttons — they are inside the MCQ block
  // Each option button contains a circular span with the letter
  const optionLocator = page.locator(`button:has(span:text-is("${letter}"))`).first();
  const visible = await optionLocator.isVisible().catch(() => false);
  if (visible) {
    await optionLocator.click();
    return true;
  }
  return false;
}

/**
 * Clicks option A twice — likely wrong on most cards.
 * Used for testing wrong-answer flows.
 */
export async function answerMCQWrong(page) {
  // Option A is the first MCQ pill button
  const optionA = page.locator('button:has(span:text-is("A"))').first();
  const visible = await optionA.isVisible({ timeout: 5000 }).catch(() => false);
  if (visible) {
    await optionA.click();
    // Wait for the wrong-answer feedback timer (WRONG_FEEDBACK_MS = 1800ms) then a bit more
    await page.waitForTimeout(2200);
    // Click A again on the replacement question
    const optionAAgain = page.locator('button:has(span:text-is("A"))').first();
    const visibleAgain = await optionAAgain.isVisible({ timeout: 5000 }).catch(() => false);
    if (visibleAgain) {
      await optionAAgain.click();
    }
  }
}

/**
 * Clicks the Next button (contains "Next" text with ChevronRight icon).
 * Safe to call when Next may not be visible yet — will wait up to 5s.
 */
export async function clickNext(page) {
  // "Next" button text — matches the i18n key "learning.next" = "Next"
  const btn = page.getByRole('button', { name: /^Next/ }).first();
  await btn.waitFor({ state: 'visible', timeout: 5000 }).catch(() => {});
  const enabled = await btn.isEnabled().catch(() => false);
  if (enabled) {
    // Use a short action timeout to avoid blocking if the button becomes disabled
    // between the isEnabled check and the actual click (React re-render race condition).
    await btn.click({ timeout: 3000 }).catch(() => {});
  }
}

/**
 * Clicks the Finish & Check button (i18n key "learning.finishCards" = "Finish Cards").
 * Also handles "Check My Understanding" in remediation mode.
 */
export async function clickFinish(page) {
  const btn = page.getByRole('button', {
    name: /Finish Cards|Check My Understanding|Finish &/i,
  }).first();
  await btn.waitFor({ state: 'visible', timeout: 10000 }).catch(() => {});
  const enabled = await btn.isEnabled().catch(() => false);
  if (enabled) {
    await btn.click();
  }
}

/**
 * Advances through all cards on the current page, handling MCQs along the way.
 * Clicks the correct MCQ answer (when sessionId is provided), then Next, until
 * the Finish button appears, then calls clickFinish.
 *
 * @param {import('@playwright/test').Page} page
 * @param {string|null} sessionId
 * @param {number} maxCards Safety cap — stops after this many iterations
 */
export async function advanceThroughAllCards(page, sessionId = null, maxCards = 20) {
  for (let i = 0; i < maxCards; i++) {
    // Check if Finish button is visible (last card)
    const finishVisible = await page
      .getByRole('button', { name: /Finish Cards|Check My Understanding/i })
      .first()
      .isVisible({ timeout: 1000 })
      .catch(() => false);

    if (finishVisible) {
      await clickFinish(page);
      return;
    }

    // Try to answer MCQ if present
    if (sessionId) {
      await answerMCQCorrectly(page, sessionId, i).catch(() => {});
    } else {
      // Try clicking A — if wrong we still move along
      const optA = page.locator('button:has(span:text-is("A"))').first();
      const visible = await optA.isVisible({ timeout: 1000 }).catch(() => false);
      if (visible) {
        await optA.click();
        await page.waitForTimeout(500);
      }
    }

    // Try "Got it!" for FUN cards
    const gotIt = page.getByRole('button', { name: /Got it/i }).first();
    const gotItVisible = await gotIt.isVisible({ timeout: 500 }).catch(() => false);
    if (gotItVisible) {
      await gotIt.click();
      await page.waitForTimeout(300);
    }

    // Click Next
    await clickNext(page);
    await page.waitForTimeout(600);
  }
}
