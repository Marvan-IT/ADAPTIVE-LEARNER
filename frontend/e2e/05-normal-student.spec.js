/**
 * Spec 05 — Normal Student Navigation
 *
 * Business criteria:
 *   - Previous button is disabled on the first card (no going back before start)
 *   - Difficulty bias buttons ("Too Easy" / "Too Hard") appear after card 1 is passed
 *   - Student can navigate back to the previous card
 */

import { test, expect } from '@playwright/test';
import {
  createStudent,
  navigateToLearn,
  waitForCards,
  answerMCQCorrectly,
  clickNext,
  CONCEPT_C1S1,
} from './helpers.js';

test.describe('Normal Student Navigation', () => {

  test('previous button is disabled on card 0', async ({ page }) => {
    const studentId = await createStudent('NormalStudent01');
    await navigateToLearn(page, studentId, CONCEPT_C1S1);
    await waitForCards(page);

    // "Previous" button — i18n key "learning.previous" = "Previous"
    const prevBtn = page.getByRole('button', { name: /Previous/i }).first();
    await prevBtn.waitFor({ state: 'visible', timeout: 10_000 });

    // On card 0 the button is rendered with cursor: not-allowed and opacity: 0.5
    // Playwright reports disabled=true because of the disabled attribute
    await expect(prevBtn).toBeDisabled();
  });

  test('difficulty bias buttons appear after advancing from card 1', async ({ page }) => {
    const studentId = await createStudent('NormalStudent02');

    // Intercept the browser's session creation to get the real session ID
    let browserSessionId = null;
    await page.route('**/api/v2/sessions', async (route) => {
      const req = route.request();
      if (req.method() === 'POST' && !req.url().includes('/cards')) {
        const response = await route.fetch();
        const clone = await response.json();
        if (clone.concept_id === CONCEPT_C1S1) browserSessionId = clone.id;
        await route.fulfill({ response, body: JSON.stringify(clone), contentType: 'application/json' });
      } else {
        await route.continue();
      }
    });

    await navigateToLearn(page, studentId, CONCEPT_C1S1);
    await waitForCards(page);
    await page.unroute('**/api/v2/sessions');

    // Answer card 0 MCQ correctly so Next is enabled (using the browser's real session)
    if (browserSessionId) {
      await answerMCQCorrectly(page, browserSessionId, 0).catch(() => {});
    }

    // Also try "Got it!" if it's a FUN card
    const gotIt = page.getByRole('button', { name: /Got it/i }).first();
    if (await gotIt.isVisible({ timeout: 500 }).catch(() => false)) {
      await gotIt.click();
    }

    // Advance to card 1
    await clickNext(page);
    await page.waitForTimeout(1000);

    // The difficulty bias buttons are rendered when currentCardIndex > 0
    // They read "Too Easy" and "Too Hard"
    const tooEasy = page.getByRole('button', { name: 'Too Easy' });
    const tooHard = page.getByRole('button', { name: 'Too Hard' });

    await expect(tooEasy.first()).toBeVisible({ timeout: 8_000 });
    await expect(tooHard.first()).toBeVisible({ timeout: 8_000 });
  });

  test('can navigate back to previous card', async ({ page }) => {
    const studentId = await createStudent('NormalStudent03');

    // Intercept the browser's session creation to get the real session ID
    let browserSessionId = null;
    await page.route('**/api/v2/sessions', async (route) => {
      const req = route.request();
      if (req.method() === 'POST' && !req.url().includes('/cards')) {
        const response = await route.fetch();
        const clone = await response.json();
        if (clone.concept_id === CONCEPT_C1S1) browserSessionId = clone.id;
        await route.fulfill({ response, body: JSON.stringify(clone), contentType: 'application/json' });
      } else {
        await route.continue();
      }
    });

    await navigateToLearn(page, studentId, CONCEPT_C1S1);
    await waitForCards(page);
    await page.unroute('**/api/v2/sessions');

    // Capture the first card body before advancing
    const firstCardBody = page.locator('.markdown-content').first();
    await firstCardBody.waitFor({ state: 'visible', timeout: 10_000 });
    const firstBodyText = await firstCardBody.innerText();

    // Answer card 0 MCQ correctly using the browser's real session
    if (browserSessionId) {
      await answerMCQCorrectly(page, browserSessionId, 0).catch(() => {});
    }

    // Handle FUN card "Got it!" tap
    const gotIt = page.getByRole('button', { name: /Got it/i }).first();
    if (await gotIt.isVisible({ timeout: 500 }).catch(() => false)) {
      await gotIt.click();
    }

    // If Next is still disabled after MCQ attempt, try waiting a bit longer
    const nextBtn = page.getByRole('button', { name: /^Next/i }).first();
    const nextEnabled = await nextBtn.isEnabled({ timeout: 5_000 }).catch(() => false);
    if (!nextEnabled) {
      // Last resort: "Got it" on a FUN card that may not have shown yet
      const gotItFallback = page.getByRole('button', { name: /Got it/i }).first();
      if (await gotItFallback.isVisible({ timeout: 1_000 }).catch(() => false)) {
        await gotItFallback.click();
      }
    }

    // Advance to card 1
    await clickNext(page);
    await page.waitForTimeout(500);

    // Now navigate back
    const prevBtn = page.getByRole('button', { name: /Previous/i }).first();
    // Brief additional wait in case the button state update is delayed
    await page.waitForTimeout(500);
    await expect(prevBtn).toBeEnabled({ timeout: 5_000 });
    await prevBtn.click();
    await page.waitForTimeout(500);

    // We should be back at card 0 — body text should match what we saw before
    const currentBodyText = await page.locator('.markdown-content').first().innerText();
    expect(
      currentBodyText.trim(),
      'Navigating back should return to the first card'
    ).toBe(firstBodyText.trim());
  });

});
