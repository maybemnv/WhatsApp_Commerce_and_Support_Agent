import { expect, test } from "@playwright/test";

const workspaceHeaders = { "X-Workspace-ID": "workspace-demo" };
const inboundFixture = {
  event_id: "provider-event-demo-001",
  message_id: "provider-message-demo-001",
  from: "+15551234567",
  text: "Is the blue product available?",
  timestamp: "2026-08-09T10:00:00Z",
};

test.beforeEach(async ({ request }) => {
  const reset = await request.post("/demo/reset", { headers: workspaceHeaders });
  expect(reset.ok()).toBeTruthy();
});

test("desktop/mobile workbench completes the fixture checkout story", async ({ page }) => {
  await page.goto("/demo");
  await page.getByRole("button", { name: "Load inbound fixture" }).click();
  await expect(page.locator("#conversationRow")).toContainText("Is the blue product available?");

  await page.getByRole("button", { name: "Ask catalog" }).click();
  await expect(page.locator("#selectButton")).toBeEnabled();
  await page.getByRole("button", { name: "Select 2" }).click();
  await expect(page.locator("#confirmButton")).toBeEnabled();
  await page.getByRole("button", { name: "Confirm and create link" }).click();

  await expect(page.locator("#paymentBadge")).toHaveText("LINK CREATED");
  await expect(page.locator("#message")).toContainText("Payment is not confirmed");
});

test("policy failure is visible and cannot advance downstream actions", async ({ page, request }) => {
  const accepted = await request.post("/webhooks/meta_cloud", {
    headers: workspaceHeaders,
    data: inboundFixture,
  });
  expect(accepted.ok()).toBeTruthy();
  const conversationId = (await accepted.json()).conversation_id as string;
  const optedOut = await request.post(`/inbox/${conversationId}/policy/opt-out`, {
    headers: workspaceHeaders,
  });
  expect(optedOut.ok()).toBeTruthy();

  await page.goto("/demo");
  await page.getByRole("button", { name: "Load inbound fixture" }).click();
  await page.getByRole("button", { name: "Ask catalog" }).click();

  await expect(page.locator("#errorStatus")).toBeVisible();
  await expect(page.locator("#errorStatus")).toHaveText("outbound blocked: opt-out is active");
  await expect(page.locator("#selectButton")).toBeDisabled();
  await expect(page.locator("#confirmButton")).toBeDisabled();
});

test("mobile layout keeps the fixture controls reachable without horizontal overflow", async ({ page }) => {
  await page.goto("/demo");
  await expect(page.locator("#loadButton")).toBeVisible();
  await page.getByRole("button", { name: "Load inbound fixture" }).click();
  await page.getByRole("button", { name: "Ask catalog" }).click();
  await page.getByRole("button", { name: "Select 2" }).click();
  await page.getByRole("button", { name: "Confirm and create link" }).click();

  const fitsViewport = await page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth,
  );
  expect(fitsViewport).toBeTruthy();
  await expect(page.locator("#confirmButton")).toBeVisible();
});
