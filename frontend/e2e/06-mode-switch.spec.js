/**
 * Spec 06 — Mode Switch Stability
 *
 * Business criteria:
 *   - The app remains stable (no blank screen, no crash) during rapid card advancement
 *   - After multiple wrong answers the app still displays meaningful content
 *
 * Mode switches (SLOW/FAST/STRUGGLING/NORMAL) happen server-side between sections.
 * These tests validate that the UI handles any mode without crashing.
 */

import { test, expect } from '@playwright/test';
import {
  createStudent,
  navigateToLearn,
  waitForCards,
  CONCEPT_C1S1,
} from './helpers.js';

// ---------------------------------------------------------------------------
// Helper: click the first enabled "advance" button visible on the page
// (handles Next, Got it!, Finish Cards, or any MCQ option)
// ---------------------------------------------------------------------------
async function advanceOnce(page) {
  // Try "Got it!" first (FUN card)
  const gotIt = page.getByRole('button', { name: /Got it/i }).first();
  if (await gotIt.isVisible({ timeout: 300 }).catch(() => false)) {
    if (await gotIt.isEnabled().catch(() => false)) {
      await gotIt.click();
      return 'got-it';
    }
  }

  // Try Next (enabled)
  const nextBtn = page.getByRole('button', { name: /^Next/i }).first();
  const nextEnabled = await nextBtn.isEnabled({ timeout: 300 }).catch(() => false);
  if (nextEnabled) {
    await nextBtn.click();
    return 'next';
  }

  // Try Finish Cards (last card)
  const finishBtn = page.getByRole('button', { name: /Finish Cards|Check My Understanding/i }).first();
  if (await finishBtn.isVisible({ timeout: 300 }).catch(() => false)) {
    if (await finishBtn.isEnabled().catch(() => false)) {
      await finishBtn.click();
      return 'finish';
    }
  }

  // No button active — try clicking option A to unlock Next
  const optionA = page.locator('button:has(span:text-is("A"))').first();
  if (await optionA.isVisible({ timeout: 300 }).catch(() => false)) {
    await optionA.click();
    await page.waitForTimeout(300);
    return 'mcq-a';
  }

  return null;
}

test.describe('Mode Switch Stability', () => {

  test('UI survives rapid card advancement without blank screen', async ({ page }) => {
    const studentId = await createStudent('ModeSwitchStudent01');
    await navigateToLearn(page, studentId, CONCEPT_C1S1);
    await waitForCards(page);

    for (let i = 0; i < 8; i++) {
      // Wait for any loading spinner to clear before advancing
      await page.waitForFunction(
        () => !document.body.innerText.includes('crafting') &&
              !document.body.innerText.includes('Generating'),
        { timeout: 30_000 }
      ).catch(() => {});

      const action = await advanceOnce(page);

      // After advancing, verify the page has substantial content
      const bodyText = await page.locator('body').innerText();
      expect(
        bodyText.trim().length,
        `Iteration ${i}: page should have substantial content after action "${action}"`
      ).toBeGreaterThan(100);

      // No error overlay
      const errorVisible = await page.locator('text=/Something went wrong/i').first()
        .isVisible({ timeout: 500 }).catch(() => false);
      expect(errorVisible, `Iteration ${i}: error overlay should not appear`).toBe(false);

      await page.waitForTimeout(500);

      // Stop if we reached CHECKING phase (Socratic chat)
      const socraticVisible = await page.locator('text=/Practice Chat|ADA is preparing/i').first()
        .isVisible({ timeout: 500 }).catch(() => false);
      if (socraticVisible) break;
    }
  });

  test('app stable after wrong answers pattern', async ({ page }) => {
    const studentId = await createStudent('ModeSwitchStudent02');
    await navigateToLearn(page, studentId, CONCEPT_C1S1);
    await waitForCards(page);

    // Answer wrong 3 times across different cards
    let wrongCount = 0;
    for (let card = 0; card < 3 && wrongCount < 3; card++) {
      const optionA = page.locator('button:has(span:text-is("A"))').first();
      const visible = await optionA.isVisible({ timeout: 5_000 }).catch(() => false);
      if (visible) {
        await optionA.click();
        wrongCount++;
        await page.waitForTimeout(2200); // wait for WRONG_FEEDBACK_MS + replacement

        // Advance to next card if possible
        await advanceOnce(page);
        await page.waitForTimeout(500);
      } else {
        // No MCQ on this card — just advance
        await advanceOnce(page);
        await page.waitForTimeout(500);
      }
    }

    // App must still render substantial content
    const bodyText = await page.locator('body').innerText();
    expect(
      bodyText.trim().length,
      'App should still show > 200 chars of content after wrong answers'
    ).toBeGreaterThan(200);
  });

});
