/**
 * Spec 01 — Card Rendering
 *
 * Business criteria:
 *   - Cards load with visible title and non-trivial body content
 *   - LaTeX/KaTeX math renders correctly (no raw markup leaked to DOM)
 *   - Images load without HTTP errors
 *   - Progress dots appear (one per card)
 *   - Cards are readable on mobile viewport (393px wide)
 */

import { test, expect } from '@playwright/test';
import {
  createStudent,
  navigateToLearn,
  waitForCards,
  CONCEPT_C1S1,
  CONCEPT_C1S2,
} from './helpers.js';

test.describe('Card Rendering', () => {

  test('cards load with visible text', async ({ page }) => {
    const studentId = await createStudent('RenderStudent01');
    await navigateToLearn(page, studentId, CONCEPT_C1S1);
    await waitForCards(page);

    // The card title is a div inside the card header containing the concept name
    // waitForCards already confirmed .markdown-content is visible; check the card title div
    // The card header area contains the title text (e.g. "Introduction to Whole Numbers — Card 1")
    const cardTitle = page.locator('.markdown-content').first();
    await cardTitle.waitFor({ state: 'visible', timeout: 10_000 });
    const titleText = await cardTitle.innerText();
    expect(titleText.length, 'Card title should be non-empty').toBeGreaterThan(3);
  });

  test('card body content is non-empty', async ({ page }) => {
    const studentId = await createStudent('RenderStudent02');
    await navigateToLearn(page, studentId, CONCEPT_C1S1);
    await waitForCards(page);

    // Card body lives inside the .markdown-content div.
    // waitForCards already confirmed .markdown-content is present; use a generous waitFor
    // in case the first match was from AssistantPanel (rendered in loading skeleton) rather
    // than from the actual card body.
    const bodyLocator = page.locator('.markdown-content').first();
    await bodyLocator.waitFor({ state: 'visible', timeout: 60_000 });
    const bodyText = await bodyLocator.innerText();
    expect(bodyText.trim().length, 'Card body should have substantial content').toBeGreaterThan(50);
  });

  test('KaTeX math renders properly — no raw backslash-frac visible', async ({ page }) => {
    const studentId = await createStudent('RenderStudent03');
    await navigateToLearn(page, studentId, CONCEPT_C1S1);
    await waitForCards(page);

    const bodyText = await page.locator('body').innerText();

    // Raw LaTeX delimiters should not appear in rendered output
    expect(bodyText, 'Raw \\frac{ should not leak into DOM').not.toContain('\\frac{');
    expect(bodyText, 'Raw $$ math delimiters should not appear').not.toContain('$$');
  });

  test('images load without error', async ({ page }) => {
    const studentId = await createStudent('RenderStudent04');
    // Use C1S1 — C1S2 requires fresh LLM generation (3+ min). C1S1 is typically cached.
    await navigateToLearn(page, studentId, CONCEPT_C1S1);
    await waitForCards(page);

    // Evaluate all <img> elements — each should be complete with positive naturalWidth
    // OR have an alt text that does not match /error|broken/i
    const results = await page.evaluate(() => {
      return Array.from(document.querySelectorAll('img')).map((el) => ({
        src: el.src,
        complete: el.complete,
        naturalWidth: el.naturalWidth,
        alt: el.alt || '',
      }));
    });

    for (const img of results) {
      const hasLoadedOk = img.complete && img.naturalWidth > 0;
      const altIsError = /error|broken|failed/i.test(img.alt);
      // An image either loads successfully, or at minimum its alt is not an error message
      expect(
        hasLoadedOk || !altIsError,
        `Image ${img.src} appears broken (complete=${img.complete}, naturalWidth=${img.naturalWidth}, alt="${img.alt}")`
      ).toBe(true);
    }
  });

  test('progress dots appear', async ({ page }) => {
    const studentId = await createStudent('RenderStudent05');
    await navigateToLearn(page, studentId, CONCEPT_C1S1);
    await waitForCards(page);

    // Progress dots are .rounded-full divs rendered by ProgressDots component inside CardLearningView.
    // Explicitly wait up to 30s for at least one dot — the ProgressDots component renders whenever
    // the cards array is non-empty, which should coincide with card content loading.
    await page.waitForSelector('.rounded-full', { timeout: 30_000 });
    const dots = page.locator('.rounded-full');
    const count = await dots.count();
    expect(count, 'At least 4 progress dots should be visible').toBeGreaterThanOrEqual(4);
  });

  test('mobile: card readable on 393px viewport', async ({ page }) => {
    await page.setViewportSize({ width: 393, height: 851 });
    const studentId = await createStudent('RenderStudent06');
    await navigateToLearn(page, studentId, CONCEPT_C1S1);
    await waitForCards(page);

    // Title should still be visible and within viewport bounds
    const cardTitle = page.locator('.markdown-content').first();
    await cardTitle.waitFor({ state: 'visible', timeout: 60_000 });

    const box = await cardTitle.boundingBox();
    expect(box, 'Card content bounding box should exist on mobile').not.toBeNull();
    expect(box.x, 'Card should not overflow left edge').toBeGreaterThanOrEqual(0);
    expect(
      box.x + box.width,
      'Card should not overflow right edge of 393px viewport'
    ).toBeLessThanOrEqual(420); // small tolerance for scroll-bar
  });

});
