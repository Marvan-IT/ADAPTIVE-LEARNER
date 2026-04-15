// @ts-check
import { test, expect } from "@playwright/test";

const ADMIN_EMAIL = "muhammed.marvan@hightekers.com";
const ADMIN_PASSWORD = "Admin@1234";

async function loginAsAdmin(page) {
  await page.goto("/login");
  await page.locator('input[type="email"]').fill(ADMIN_EMAIL);
  await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: /log in/i }).click();
  await page.waitForURL(/\/(map|admin)/, { timeout: 15000 });
  if (!page.url().includes("/admin")) {
    await page.goto("/admin");
  }
}

test.describe("Admin Pages", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test("admin dashboard loads", async ({ page }) => {
    await page.goto("/admin");
    await page.waitForLoadState("domcontentloaded");
    await expect(page.getByText(/admin|console|dashboard/i).first()).toBeVisible({ timeout: 10000 });
  });

  test("admin students page loads", async ({ page }) => {
    await page.goto("/admin/students");
    await page.waitForLoadState("domcontentloaded");
    await expect(page.locator("table, [class*='student'], [class*='Student']").first()).toBeVisible({ timeout: 15000 });
  });

  test("admin sessions page loads", async ({ page }) => {
    await page.goto("/admin/sessions");
    await page.waitForLoadState("domcontentloaded");
    await expect(page.locator("body")).toBeVisible();
    const content = await page.content();
    expect(content.length).toBeGreaterThan(500);
  });

  test("admin analytics page loads", async ({ page }) => {
    await page.goto("/admin/analytics");
    await page.waitForLoadState("domcontentloaded");
    await expect(page.locator("body")).toBeVisible();
    const content = await page.content();
    expect(content.length).toBeGreaterThan(500);
  });

  test("admin settings page loads", async ({ page }) => {
    await page.goto("/admin/settings");
    await page.waitForLoadState("domcontentloaded");
    await expect(page.locator("body")).toBeVisible();
    const content = await page.content();
    expect(content.length).toBeGreaterThan(500);
  });

  test("admin page shows Adaptive Learner branding", async ({ page }) => {
    await page.goto("/admin");
    await page.waitForLoadState("domcontentloaded");
    const brandText = page.getByText(/adaptive learner/i).first();
    await expect(brandText).toBeVisible({ timeout: 10000 });
  });
});
