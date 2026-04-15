// @ts-check
import { test, expect } from "@playwright/test";

const TEST_EMAIL = "manujaleel007@gmail.com";
const TEST_PASSWORD = "Marvan@1234";

test.describe("Auth Flow", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/login", { waitUntil: "domcontentloaded" });
    await page.evaluate(() => {
      localStorage.removeItem("ada_refresh_token");
      localStorage.removeItem("ada_student_id");
    });
    await page.reload({ waitUntil: "domcontentloaded" });
  });

  test("login page renders correctly", async ({ page }) => {
    await page.goto("/login");
    await page.waitForLoadState("domcontentloaded");
    // Should have email and password inputs
    await expect(page.locator('input[type="email"]')).toBeVisible();
    await expect(page.locator('input[type="password"]')).toBeVisible();
    // Should have a Log In button
    await expect(page.getByRole("button", { name: /log in/i })).toBeVisible();
    // Should have register link
    await expect(page.getByText(/create account/i)).toBeVisible();
    // Title should be Adaptive Learner
    await expect(page).toHaveTitle("Adaptive Learner");
  });

  test("login with valid credentials redirects to app", async ({ page }) => {
    await page.goto("/login");
    await page.locator('input[type="email"]').fill(TEST_EMAIL);
    await page.locator('input[type="password"]').fill(TEST_PASSWORD);
    await page.getByRole("button", { name: /log in/i }).click();
    await page.waitForURL(/\/(map|admin)/, { timeout: 15000 });
    expect(page.url()).toMatch(/\/(map|admin)/);
  });

  test("login with invalid credentials shows error", async ({ page }) => {
    await page.goto("/login");
    await page.locator('input[type="email"]').fill("wrong@test.com");
    await page.locator('input[type="password"]').fill("wrongpassword");
    await page.getByRole("button", { name: /log in/i }).click();
    await expect(page.getByRole("alert")).toBeVisible({ timeout: 10000 });
  });

  test("navigate to register page", async ({ page }) => {
    await page.goto("/login");
    await page.getByText(/create account/i).click();
    await page.waitForURL("/register");
    await expect(page.locator('input[type="email"]')).toBeVisible();
  });

  test("navigate to forgot password page", async ({ page }) => {
    await page.goto("/login");
    await page.getByText(/forgot password/i).click();
    await page.waitForURL("/forgot-password");
    await expect(page.locator('input[type="email"]')).toBeVisible();
  });

  test("register page renders correctly", async ({ page }) => {
    await page.goto("/register");
    await page.waitForLoadState("domcontentloaded");
    // Should have email input
    await expect(page.locator('input[type="email"]')).toBeVisible();
    // Should have a sign up button
    const submitBtn = page.getByRole("button", { name: /sign up/i });
    await expect(submitBtn).toBeVisible();
    // Should have login link
    await expect(page.getByText(/sign in|log in/i).first()).toBeVisible();
  });

  test("forgot password page renders correctly", async ({ page }) => {
    await page.goto("/forgot-password");
    await expect(page.locator('input[type="email"]')).toBeVisible();
    const submitBtn = page.getByRole("button", { name: /send|reset/i });
    await expect(submitBtn).toBeVisible();
  });

  test("unauthenticated user is redirected to login", async ({ page }) => {
    await page.goto("/map");
    await page.waitForURL(/\/login/, { timeout: 10000 });
    expect(page.url()).toContain("/login");
  });

  test("logout flow works", async ({ page }) => {
    // Login first
    await page.goto("/login");
    await page.locator('input[type="email"]').fill(TEST_EMAIL);
    await page.locator('input[type="password"]').fill(TEST_PASSWORD);
    await page.getByRole("button", { name: /log in/i }).click();
    await page.waitForURL(/\/(map|admin)/, { timeout: 15000 });

    // Logout is in the user dropdown in the top-right of StudentTopBar
    // Find the last button in the header that looks like a user menu trigger
    const header = page.locator("header").first();
    const buttons = header.locator("button");
    const lastBtn = buttons.last();
    await lastBtn.click();
    await page.waitForTimeout(300);
    // Now click the Logout menu item
    await page.getByRole("menuitem", { name: /logout/i }).or(page.getByText(/logout/i)).first().click({ timeout: 5000 });
    await page.waitForURL(/\/login/, { timeout: 10000 });
    expect(page.url()).toContain("/login");
  });
});
