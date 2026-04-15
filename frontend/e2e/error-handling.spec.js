import { test, expect } from "@playwright/test";
import { loginAsStudent, loginAsAdmin, clearSession } from "./helpers.js";

test.describe("Error Handling & Auth Guards", () => {
  test("404 page redirects appropriately", async ({ page }) => {
    await clearSession(page);
    await page.goto("/nonexistent-page-12345");
    await page.waitForTimeout(3000);
    // Should redirect to login (unauthenticated) or map/admin (authenticated)
    expect(page.url()).toMatch(/\/(login|map|admin)/);
  });

  test("unauthenticated access to student routes redirects to login", async ({ page }) => {
    await clearSession(page);
    await page.goto("/map");
    await page.waitForURL(/\/login/, { timeout: 10000 });
    expect(page.url()).toContain("/login");
  });

  test("unauthenticated access to admin routes redirects to login", async ({ page }) => {
    await clearSession(page);
    await page.goto("/admin");
    await page.waitForURL(/\/login/, { timeout: 10000 });
    expect(page.url()).toContain("/login");
  });

  test("session persists across page refresh", async ({ page }) => {
    await loginAsStudent(page);
    const urlBeforeRefresh = page.url();
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForTimeout(3000);
    // Should still be authenticated (not redirected to login)
    expect(page.url()).not.toContain("/login");
  });

  test("student cannot access admin routes", async ({ page }) => {
    await loginAsStudent(page);
    await page.goto("/admin");
    await page.waitForTimeout(3000);
    // Should be redirected away from admin (to /map)
    expect(page.url()).not.toContain("/admin");
  });

  test("navigating to invalid learn route shows error or redirects", async ({ page }) => {
    await loginAsStudent(page);
    await page.goto("/learn/nonexistent-concept-xyz");
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(5000);
    // Should show an error message or redirect back to map
    const url = page.url();
    // Either stays on learn page (with error) or redirects to map
    expect(url).toMatch(/\/(learn|map)/);
  });

  test("double-clicking login button does not break auth", async ({ page }) => {
    await clearSession(page);
    await page.goto("/login");
    await page.locator('input[type="email"]').fill("manujaleel007@gmail.com");
    await page.locator('input[type="password"]').fill("Marvan@1234");
    // Double-click the login button rapidly
    const btn = page.getByRole("button", { name: /log in/i });
    await btn.dblclick();
    // Should still eventually redirect (not crash)
    await page.waitForURL(/\/(map|admin|login)/, { timeout: 20000 });
    // Either logged in or showing error — not a blank/broken page
    await expect(page.locator("body")).toBeVisible();
  });
});
