/**
 * Spec 08 — Complete Journey
 *
 * Business criteria:
 *   - The welcome page loads and shows the ADA branding/tagline
 *   - The concept map page loads and lists concept names
 *   - A student can navigate from cards through the Socratic chat to a final
 *     result screen (Mastered / review / score) without hitting an error
 */

import { test, expect } from '@playwright/test';
import {
  createStudent,
  createSession,
  navigateToLearn,
  waitForCards,
  answerMCQCorrectly,
  CONCEPT_C1S1,
} from './helpers.js';

// ---------------------------------------------------------------------------
// Internal: advance through all cards then answer the Socratic chat
// ---------------------------------------------------------------------------
async function completeFullJourney(page, sessionId) {
  // Phase 1: Cards
  let iterations = 0;
  while (iterations < 25) {
    iterations++;

    // Wait for any in-flight loading to complete
    await page.waitForFunction(
      () => !document.body.innerText.includes('crafting') &&
            !document.body.innerText.includes('Generating'),
      { timeout: 30_000 }
    ).catch(() => {});

    // Check if we've transitioned to CHECKING / COMPLETED / ATTEMPTS_EXHAUSTED
    const bodyText = await page.locator('body').innerText();
    if (
      /Practice Chat|ADA is preparing|Mastered|Back to Map|That was tough/i.test(bodyText)
    ) break;

    // Try answering MCQ correctly
    if (sessionId) {
      await answerMCQCorrectly(page, sessionId, iterations - 1).catch(() => {});
    }

    // Handle FUN card "Got it!"
    const gotIt = page.getByRole('button', { name: /Got it/i }).first();
    if (await gotIt.isVisible({ timeout: 300 }).catch(() => false)) {
      if (await gotIt.isEnabled().catch(() => false)) await gotIt.click();
      await page.waitForTimeout(300);
    }

    // Click Finish if on last card
    const finishBtn = page.getByRole('button', { name: /Finish Cards|Check My Understanding/i }).first();
    if (await finishBtn.isVisible({ timeout: 300 }).catch(() => false)) {
      if (await finishBtn.isEnabled().catch(() => false)) {
        await finishBtn.click();
        await page.waitForTimeout(2_000);
        break;
      }
    }

    // Click Next
    const nextBtn = page.getByRole('button', { name: /^Next/i }).first();
    if (await nextBtn.isEnabled({ timeout: 500 }).catch(() => false)) {
      await nextBtn.click();
    }

    await page.waitForTimeout(600);
  }

  // Phase 2: Socratic chat — send 3 answers
  const chatInput = page.locator('textarea, input[placeholder*="answer" i], input[placeholder*="Type" i]').first();
  const chatVisible = await chatInput.isVisible({ timeout: 15_000 }).catch(() => false);

  if (chatVisible) {
    const answers = [
      'Whole numbers are non-negative integers like 0, 1, 2, 3.',
      'Place value means the position of a digit determines its value.',
      'We can count, compare, and order whole numbers on a number line.',
    ];
    for (const answer of answers) {
      const field = page.locator('textarea, input[placeholder*="answer" i], input[placeholder*="Type" i]').first();
      if (!await field.isVisible({ timeout: 4_000 }).catch(() => false)) break;
      await field.fill(answer);
      await field.press('Enter');
      await page.waitForTimeout(5_000);

      // Stop early if we hit a terminal state
      const txt = await page.locator('body').innerText();
      if (/Mastered|Back to Map|That was tough|review|score/i.test(txt)) break;
    }
  }
}

test.describe('Complete Journey', () => {

  test('welcome page loads with content', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {});

    const bodyText = await page.locator('body').innerText();
    expect(bodyText.trim().length, 'Welcome page should have content').toBeGreaterThan(50);

    // The app title "ADA" should be visible (t("app.title"))
    const title = page.locator('h1:has-text("ADA"), [style*="font-size: 3.25rem"]');
    const titleVisible = await title.first().isVisible({ timeout: 5_000 }).catch(() => false);
    expect(titleVisible, 'ADA title should be visible on the welcome page').toBe(true);
  });

  test('concept map shows concepts', async ({ page }) => {
    // Set a student in localStorage first so the map loads correctly
    const studentId = await createStudent('JourneyMapStudent');
    await page.goto('/');
    await page.evaluate((id) => localStorage.setItem('ada_student_id', id), studentId);
    await page.goto('/map');
    await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {});
    await page.waitForTimeout(2_000); // Allow graph to render

    const bodyText = await page.locator('body').innerText();
    const hasConcepts = /concept|prealgebra|whole numbers|chapter|section/i.test(bodyText);
    expect(hasConcepts, 'Concept map page should mention concepts or textbook content').toBe(true);
  });

  test('full card-to-end-state journey — no crash', async ({ page }) => {
    const studentId = await createStudent('JourneyStudent01');
    const session = await createSession(studentId, CONCEPT_C1S1);

    await navigateToLearn(page, studentId, CONCEPT_C1S1);
    await waitForCards(page);

    await completeFullJourney(page, session.id);

    // Final assertion: the page should be in a recognizable terminal/progress state
    const finalText = await page.locator('body').innerText();

    const isTerminalState = /Mastered|Concept Mastered|review|practice|score|%|Back to Map|That was tough|Practice Chat/i.test(finalText);
    expect(isTerminalState, 'Journey should end in a recognizable state').toBe(true);

    // No generic crash error
    const hasCrashError = /Something went wrong/i.test(finalText);
    expect(hasCrashError, '"Something went wrong" error should not appear').toBe(false);
  });

});
