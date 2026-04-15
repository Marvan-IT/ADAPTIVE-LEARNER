export const STUDENT = {
  email: "manujaleel007@gmail.com",
  password: "Marvan@1234",
};

export const ADMIN = {
  email: "muhammed.marvan@hightekers.com",
  password: "Admin@1234",
};

/**
 * Login as the test student account.
 * After login, the page will be at /map (student) or /admin (admin role).
 */
export async function loginAsStudent(page) {
  await page.goto("/login");
  await page.locator('input[type="email"]').fill(STUDENT.email);
  await page.locator('input[type="password"]').fill(STUDENT.password);
  await page.getByRole("button", { name: /log in/i }).click();
  await page.waitForURL(/\/(map|admin)/, { timeout: 15000 });
  // If redirected to admin (dual-role account), go to student area
  if (page.url().includes("/admin")) {
    await page.goto("/map");
  }
}

/**
 * Login as the test admin account.
 * After login, the page will be at /admin.
 */
export async function loginAsAdmin(page) {
  await page.goto("/login");
  await page.locator('input[type="email"]').fill(ADMIN.email);
  await page.locator('input[type="password"]').fill(ADMIN.password);
  await page.getByRole("button", { name: /log in/i }).click();
  await page.waitForURL(/\/(map|admin)/, { timeout: 15000 });
  if (!page.url().includes("/admin")) {
    await page.goto("/admin");
  }
}

/**
 * Clear auth state so the next test starts fresh.
 */
export async function clearSession(page) {
  await page.goto("/login", { waitUntil: "domcontentloaded" });
  await page.evaluate(() => {
    localStorage.removeItem("ada_refresh_token");
    localStorage.removeItem("ada_student_id");
  });
  await page.reload({ waitUntil: "domcontentloaded" });
}
