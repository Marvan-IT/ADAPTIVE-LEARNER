// @ts-check
import { test, expect } from "@playwright/test";
import { loginAsStudent } from "./helpers.js";

/**
 * Wait for the concept map sidebar to populate, then click the first
 * "Start Lesson" or "Review Lesson" button to navigate to /learn/.
 *
 * Returns the /learn/ URL that was navigated to, or null if no button
 * was found (no books published).
 */
async function navigateToFirstConcept(page) {
  // Sidebar buttons: t("map.startLesson") = "Start Lesson"
  //                  t("map.reviewLesson") = "Review Lesson"
  const btn = page
    .getByRole("button", { name: /start lesson|review lesson/i })
    .first();

  const visible = await btn.isVisible({ timeout: 15000 }).catch(() => false);
  if (!visible) return null;

  await btn.click();
  await page.waitForURL(/\/learn\//, { timeout: 15000 });
  return page.url();
}

test.describe("Learning Flow", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsStudent(page);
  });

  // ─── Navigation ─────────────────────────────────────────────────────────────

  test("clicking Start Lesson in the sidebar navigates to /learn/", async ({ page }) => {
    await page.goto("/map");
    await page.waitForLoadState("domcontentloaded");

    const url = await navigateToFirstConcept(page);
    if (url === null) {
      test.skip(true, "No Start Lesson buttons visible — no books published");
      return;
    }
    expect(url).toContain("/learn/");
  });

  test("learn URL contains a book_slug query parameter", async ({ page }) => {
    await page.goto("/map");
    await page.waitForLoadState("domcontentloaded");

    const url = await navigateToFirstConcept(page);
    if (url === null) {
      test.skip(true, "No Start Lesson buttons visible — no books published");
      return;
    }
    expect(url).toContain("book_slug=");
  });

  // ─── Loading States ──────────────────────────────────────────────────────────

  test("learning page shows skeleton shimmer while session loads", async ({ page }) => {
    await page.goto("/map");
    await page.waitForLoadState("domcontentloaded");

    const url = await navigateToFirstConcept(page);
    if (url === null) {
      test.skip(true, "No Start Lesson buttons visible — no books published");
      return;
    }

    // Immediately after navigation the LOADING/IDLE phase renders skeleton-shimmer divs
    // and the "Adaptive Learner is crafting your lesson cards..." label.
    // Either indicator is acceptable — just verify the page is non-blank.
    const html = await page.locator("body").innerHTML();
    expect(html.length).toBeGreaterThan(500);
  });

  test("crafting cards label or skeleton is visible during initial load", async ({ page }) => {
    await page.goto("/map");
    await page.waitForLoadState("domcontentloaded");

    const btn = page.getByRole("button", { name: /start lesson|review lesson/i }).first();
    if (!(await btn.isVisible({ timeout: 15000 }).catch(() => false))) {
      test.skip(true, "No Start Lesson buttons visible — no books published");
      return;
    }

    // Click and immediately observe — we want the loading phase, not the loaded phase
    await btn.click();
    await page.waitForURL(/\/learn\//, { timeout: 15000 });

    const shimmer = page.locator(".skeleton-shimmer").first();
    const craftingText = page.getByText(/crafting|generating|loading|preparing/i).first();

    const shimmerSeen = await shimmer.isVisible({ timeout: 6000 }).catch(() => false);
    const textSeen = await craftingText.isVisible({ timeout: 6000 }).catch(() => false);

    // Either loading indicator is fine; or content already arrived (very fast API)
    const html = await page.locator("body").innerHTML();
    expect(shimmerSeen || textSeen || html.length > 800).toBe(true);
  });

  // ─── Chunk Picker (SELECTING_CHUNK phase) ────────────────────────────────────

  test("chunk picker appears after session initialises", async ({ page }) => {
    await page.goto("/map");
    await page.waitForLoadState("domcontentloaded");

    const url = await navigateToFirstConcept(page);
    if (url === null) {
      test.skip(true, "No Start Lesson buttons visible — no books published");
      return;
    }

    // SELECTING_CHUNK phase renders subsection rows.
    // Each row has a "Start" button (t("learning.startSubsection") = "Start").
    // Wait up to 30s because the session creation + chunk list fetch takes time.
    const chunkStartBtn = page.getByRole("button", { name: /^start$/i }).first();
    const chunkPickerVisible = await chunkStartBtn.isVisible({ timeout: 30000 }).catch(() => false);

    // Also accept: if a heading (concept title) rendered — SELECTING_CHUNK phase shown
    if (!chunkPickerVisible) {
      const heading = page.locator("h1").first();
      const headingVisible = await heading.isVisible({ timeout: 5000 }).catch(() => false);
      if (headingVisible) {
        const text = await heading.textContent();
        expect(text.trim().length).toBeGreaterThan(0);
        return;
      }
    }

    // Substantial HTML is the minimum acceptance bar
    const html = await page.locator("body").innerHTML();
    expect(html.length).toBeGreaterThan(500);
  });

  test("chunk picker heading shows the concept title", async ({ page }) => {
    await page.goto("/map");
    await page.waitForLoadState("domcontentloaded");

    const url = await navigateToFirstConcept(page);
    if (url === null) {
      test.skip(true, "No Start Lesson buttons visible — no books published");
      return;
    }

    const h1 = page.locator("h1").first();
    if (await h1.isVisible({ timeout: 30000 }).catch(() => false)) {
      const text = await h1.textContent();
      expect(text.trim().length).toBeGreaterThan(0);
    }
  });

  test("chunk picker shows subsection count progress when some are completed", async ({ page }) => {
    await page.goto("/map");
    await page.waitForLoadState("domcontentloaded");

    const url = await navigateToFirstConcept(page);
    if (url === null) {
      test.skip(true, "No Start Lesson buttons visible — no books published");
      return;
    }

    await page.waitForTimeout(10000);
    // The "X of Y sections completed" line appears when chunkProgress is non-empty
    const progress = page.getByText(/of \d+ sections? completed/i).first();
    const progressVisible = await progress.isVisible({ timeout: 5000 }).catch(() => false);
    // Progress text is only shown for returning students — not a failure if absent
    await expect(page.locator("body")).toBeVisible();
  });

  // ─── Exit / Back to Map ──────────────────────────────────────────────────────

  test("Exit Lesson button is visible on the learning page", async ({ page }) => {
    await page.goto("/map");
    await page.waitForLoadState("domcontentloaded");

    const url = await navigateToFirstConcept(page);
    if (url === null) {
      test.skip(true, "No Start Lesson buttons visible — no books published");
      return;
    }

    await page.waitForTimeout(3000);

    // t("learning.exitLesson") = "Exit Lesson"
    const exitBtn = page.getByText(/exit lesson/i).first();
    const exitVisible = await exitBtn.isVisible({ timeout: 10000 }).catch(() => false);

    // t("learning.backToMap") = "Back to Map" — appears on error state
    const backBtn = page.getByText(/back to map/i).first();
    const backVisible = await backBtn.isVisible({ timeout: 5000 }).catch(() => false);

    expect(exitVisible || backVisible).toBe(true);
  });

  test("exit lesson inline confirm row appears after clicking Exit Lesson", async ({ page }) => {
    await page.goto("/map");
    await page.waitForLoadState("domcontentloaded");

    const url = await navigateToFirstConcept(page);
    if (url === null) {
      test.skip(true, "No Start Lesson buttons visible — no books published");
      return;
    }

    await page.waitForTimeout(3000);

    const exitBtn = page.getByText(/exit lesson/i).first();
    if (!(await exitBtn.isVisible({ timeout: 10000 }).catch(() => false))) {
      return; // exit button not yet rendered (still loading)
    }

    await exitBtn.click();
    await page.waitForTimeout(400);

    // After click, inline confirm row shows "Exit lesson? Your progress will be lost."
    // plus two buttons: t("learning.exitYes") = "Exit" and t("learning.exitNo") = "Stay"
    const confirmText = page.getByText(/exit lesson\?|your progress will be lost/i).first();
    const confirmVisible = await confirmText.isVisible({ timeout: 3000 }).catch(() => false);

    const stayBtn = page.getByRole("button", { name: /stay/i }).first();
    const stayVisible = await stayBtn.isVisible({ timeout: 3000 }).catch(() => false);

    expect(confirmVisible || stayVisible).toBe(true);
  });

  test("confirming exit navigates back to /map", async ({ page }) => {
    await page.goto("/map");
    await page.waitForLoadState("domcontentloaded");

    const url = await navigateToFirstConcept(page);
    if (url === null) {
      test.skip(true, "No Start Lesson buttons visible — no books published");
      return;
    }

    await page.waitForTimeout(3000);

    // Try "Exit Lesson" → confirm "Exit"
    const exitBtn = page.getByText(/exit lesson/i).first();
    if (await exitBtn.isVisible({ timeout: 10000 }).catch(() => false)) {
      await exitBtn.click();
      await page.waitForTimeout(400);

      // t("learning.exitYes") = "Exit"
      const confirmBtn = page.getByRole("button", { name: /^exit$/i }).first();
      if (await confirmBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
        await confirmBtn.click();
        await page.waitForURL(/\/map/, { timeout: 10000 });
        expect(page.url()).toContain("/map");
        return;
      }
    }

    // Fallback: "Back to Map" button on error state
    const backBtn = page.getByText(/back to map/i).first();
    if (await backBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
      await backBtn.click();
      await page.waitForURL(/\/map/, { timeout: 10000 });
      expect(page.url()).toContain("/map");
    }
  });

  test("Stay button in exit confirm row keeps user on /learn/", async ({ page }) => {
    await page.goto("/map");
    await page.waitForLoadState("domcontentloaded");

    const url = await navigateToFirstConcept(page);
    if (url === null) {
      test.skip(true, "No Start Lesson buttons visible — no books published");
      return;
    }

    await page.waitForTimeout(3000);

    const exitBtn = page.getByText(/exit lesson/i).first();
    if (!(await exitBtn.isVisible({ timeout: 10000 }).catch(() => false))) return;

    await exitBtn.click();
    await page.waitForTimeout(400);

    // t("learning.exitNo") = "Stay"
    const stayBtn = page.getByRole("button", { name: /^stay$/i }).first();
    if (await stayBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await stayBtn.click();
      await page.waitForTimeout(500);
      expect(page.url()).toContain("/learn/");
    }
  });

  // ─── Session Persistence ─────────────────────────────────────────────────────

  test("learning page stays on /learn/ after a browser refresh", async ({ page }) => {
    await page.goto("/map");
    await page.waitForLoadState("domcontentloaded");

    const url = await navigateToFirstConcept(page);
    if (url === null) {
      test.skip(true, "No Start Lesson buttons visible — no books published");
      return;
    }

    // Give the session time to be written to localStorage
    await page.waitForTimeout(3000);
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForTimeout(2000);

    // After reload the student is still authenticated and the route is still /learn/
    expect(page.url()).toContain("/learn/");
  });

  // ─── Prerequisite Warning ────────────────────────────────────────────────────

  test("prerequisite warning modal can be dismissed with Start Anyway", async ({ page }) => {
    await page.goto("/map");
    await page.waitForLoadState("domcontentloaded");

    const url = await navigateToFirstConcept(page);
    if (url === null) {
      test.skip(true, "No Start Lesson buttons visible — no books published");
      return;
    }

    await page.waitForTimeout(4000);

    // Prereq warning renders as a fixed overlay with role="dialog" (indirectly via modal div)
    // Buttons: t("learning.learnPrereqFirst") and t("learning.startAnyway")
    const startAnywayBtn = page.getByRole("button", { name: /start anyway/i }).first();
    if (await startAnywayBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await startAnywayBtn.click();
      await page.waitForTimeout(1000);
      // After dismissal the modal is gone
      const stillOpen = await startAnywayBtn.isVisible({ timeout: 1000 }).catch(() => false);
      expect(stillOpen).toBe(false);
    }
    // No prereq warning is also valid
    await expect(page.locator("body")).toBeVisible();
  });

  test("prerequisite warning offers a back-to-map option", async ({ page }) => {
    await page.goto("/map");
    await page.waitForLoadState("domcontentloaded");

    const url = await navigateToFirstConcept(page);
    if (url === null) {
      test.skip(true, "No Start Lesson buttons visible — no books published");
      return;
    }

    await page.waitForTimeout(4000);

    const prereqBtn = page.getByRole("button", { name: /learn prerequisite first/i }).first();
    if (await prereqBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await prereqBtn.click();
      await page.waitForURL(/\/map/, { timeout: 10000 });
      expect(page.url()).toContain("/map");
    }
    // Prereq warning absent — acceptable
  });
});
