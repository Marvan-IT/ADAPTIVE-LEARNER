// @ts-check
import { test, expect } from "@playwright/test";

const TEST_EMAIL = "manujaleel007@gmail.com";
const TEST_PASSWORD = "Marvan@1234";

test.describe("UI Component Integration", () => {
  test("login page uses amber primary color (not purple)", async ({ page }) => {
    await page.goto("/login");
    await page.waitForLoadState("networkidle");

    // Get the computed --color-primary value
    const primaryColor = await page.evaluate(() => {
      return getComputedStyle(document.documentElement).getPropertyValue("--color-primary").trim();
    });

    // Should NOT be indigo/purple (#6366f1, #7c3aed)
    expect(primaryColor).not.toBe("#6366f1");
    expect(primaryColor).not.toBe("#7c3aed");
    // Should be amber (#d97706 light or #fbbf24 dark)
    expect(["#d97706", "#fbbf24"]).toContain(primaryColor);
  });

  test("login button renders with correct background color", async ({ page }) => {
    await page.goto("/login");
    const submitBtn = page.getByRole("button", { name: /log in/i });
    await expect(submitBtn).toBeVisible();

    // The button should have a non-purple background
    const bgColor = await submitBtn.evaluate((el) => {
      return getComputedStyle(el).backgroundColor;
    });
    // Should not contain purple-ish RGB values (99,102,241) or (124,58,237)
    expect(bgColor).not.toContain("99, 102, 241");
    expect(bgColor).not.toContain("124, 58, 237");
  });

  test("auth layout has split panel on desktop", async ({ page }) => {
    await page.goto("/login");
    await page.waitForLoadState("networkidle");

    // On desktop (1440px viewport), should have a left panel and right panel
    const aside = page.locator("aside").first();
    const isAsideVisible = await aside.isVisible();
    // On desktop, the aside (constellation panel) should be visible
    expect(isAsideVisible).toBe(true);
  });

  test("no hardcoded purple colors visible on login", async ({ page }) => {
    await page.goto("/login");
    await page.waitForLoadState("networkidle");

    // Check accent color
    const accentColor = await page.evaluate(() => {
      return getComputedStyle(document.documentElement).getPropertyValue("--color-accent").trim();
    });
    expect(accentColor).not.toBe("#8b5cf6");
    expect(accentColor).not.toBe("#a78bfa");
  });

  test("dark mode CSS variables resolve correctly", async ({ page }) => {
    await page.goto("/login");
    // Set dark theme
    await page.evaluate(() => {
      document.documentElement.setAttribute("data-theme", "dark");
    });
    await page.waitForTimeout(300);

    const primaryColor = await page.evaluate(() => {
      return getComputedStyle(document.documentElement).getPropertyValue("--color-primary").trim();
    });
    // Dark mode primary should be amber (#fbbf24)
    expect(primaryColor).toBe("#fbbf24");

    const bgColor = await page.evaluate(() => {
      return getComputedStyle(document.documentElement).getPropertyValue("--color-bg").trim();
    });
    // Dark mode bg should be dark navy
    expect(bgColor).toBe("#0c1222");
  });

  test("page title is Adaptive Learner", async ({ page }) => {
    await page.goto("/login");
    await expect(page).toHaveTitle("Adaptive Learner");
  });

  test("responsive: auth layout collapses on mobile", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto("/login");
    await page.waitForLoadState("networkidle");

    // On mobile, the aside (constellation panel) should be hidden
    const aside = page.locator("aside").first();
    const isAsideVisible = await aside.isVisible();
    expect(isAsideVisible).toBe(false);
  });
});
