const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");
const base = process.env.ZHIXUE_FRONTEND_URL || "http://127.0.0.1:5173";
const backend = process.env.ZHIXING_API_BASE || "http://127.0.0.1:8000/api/v1";
const checks = [];
const errors = [];
let completed = false;
function check(name, condition, kind = "real_backend") {
  assert.ok(condition, name);
  checks.push({ name, kind, pass: true });
}
async function login(page, role = "student") {
  await page.goto(base + "/login");
  await page
    .locator("label.zx-role")
    .filter({ has: page.locator("input[value=" + role + "]") })
    .click();
  await page.locator("input[name=account]").fill(role + "@zhixing.edu.cn");
  await page.locator("input[name=password]").fill("zhixing2026");
  await page.locator("button[type=submit]").click();
  await page.waitForURL(
    "**/" + role + "/" + (role === "student" ? "courses" : "overview"),
  );
  await page.waitForLoadState("networkidle");
}
async function ready(page) {
  await page.waitForLoadState("networkidle");
  await page
    .locator(".loading-state")
    .waitFor({ state: "hidden" })
    .catch(() => {});
}
(async () => {
  const browser = await chromium.launch({
    channel: process.env.PLAYWRIGHT_CHANNEL || "msedge",
    headless: true,
  });
  async function scenario(fn) {
    const context = await browser.newContext({
      viewport: { width: 1366, height: 768 },
      locale: "zh-CN",
    });
    const page = await context.newPage();
    page.on("pageerror", (e) => errors.push(e.message));
    try {
      await fn(page);
    } finally {
      await context.close();
    }
  }
  try {
    await scenario(async (page) => {
      await login(page);
      const token = await page.evaluate(() =>
        sessionStorage.getItem("zhixing-access-token"),
      );
      await page.getByRole("button", { name: "退出", exact: true }).click();
      await page.waitForURL("**/login");
      const r = await page.request.get(backend + "/me", {
        headers: { Authorization: "Bearer " + token },
      });
      check("在线退出撤销服务器会话", r.status() === 401);
      await page.goto(base + "/student/overview");
      await page.waitForURL("**/login");
      check("退出后受保护页面不可访问", true);
    });
    for (const role of ["student", "teacher"])
      for (const entry of role === "student"
        ? ["hub", "sidebar", "profile"]
        : ["sidebar", "profile"]) {
        await scenario(async (page) => {
          await login(page, role);
          if (entry !== "hub") {
            await page.goto(base + "/" + role + "/overview");
            await ready(page);
          }
          await page.evaluate(() => {
            sessionStorage.setItem("zhixing-course-id", "ai-intro");
            sessionStorage.setItem("zhixue-draft:test", "unsent");
          });
          await page.route("**/api/v1/auth/logout", (route) =>
            route.abort("failed"),
          );
          if (entry === "hub")
            await page
              .getByRole("button", { name: "退出", exact: true })
              .click();
          else if (entry === "sidebar")
            await page
              .getByRole("button", { name: "退出当前账号", exact: true })
              .click();
          else {
            await page.locator(".profile-button").click();
            await page.locator(".profile-menu button").click();
          }
          await page.waitForURL("**/login");
          const stored = await page.evaluate(() =>
            Object.keys(sessionStorage).filter((k) =>
              /access-token|course-id|draft:test/.test(k),
            ),
          );
          check(
            role + "/" + entry + " 退出失败仍清理身份、课程与草稿",
            stored.length === 0,
          );
          check(
            role + "/" + entry + " 退出失败明确说明服务器撤销未确认",
            (await page.locator(".session-notice").innerText()).includes(
              "无法确认",
            ),
          );
        });
      }
    await scenario(async (page) => {
      await login(page, "teacher");
      await page.goto(base + "/student/practice");
      await page.waitForURL("**/teacher/overview");
      check("教师无法进入学生工作区", true);
    });
    for (const role of ["student", "teacher"])
      await scenario(async (page) => {
        await login(page, role);
        const received = {};
        await page.route(
          "**/api/v1/" + role + "/courses/*/overview",
          async (route) => {
            const response = await route.fetch();
            const data = await response.json();
            received[data.course.id] = data;
            await new Promise((resolve) =>
              setTimeout(
                resolve,
                route.request().url().includes("machine-learning") ? 900 : 30,
              ),
            );
            await route.fulfill({ response, json: data });
          },
        );
        await page.goto(base + "/" + role + "/overview");
        await page.locator('select[aria-label="当前课程"]').waitFor();
        await page
          .locator('select[aria-label="当前课程"]')
          .selectOption("ai-intro");
        await ready(page);
        await page.waitForTimeout(1000);
        const body = await page.locator(".workspace-main").innerText();
        const expected = received["ai-intro"];
        const previous = received["machine-learning"];
        check(
          role + " 乱序响应不覆盖当前课程",
          Boolean(expected && previous) &&
            (await page.locator(".page-location").innerText()).includes(
              "人工智能导论",
            ) &&
            (role === "student"
              ? body.includes(expected.focus_summary) &&
                !body.includes(previous.focus_summary)
              : body.includes(expected.class_name) &&
                !body.includes(previous.class_name)),
        );
        await page.reload();
        await ready(page);
        check(
          role + " 刷新后恢复课程",
          (await page.locator('select[aria-label="当前课程"]').inputValue()) ===
            "ai-intro",
        );
      });
    // Minimal fixtures below validate UI error handling, not external model execution.
    await scenario(async (page) => {
      await login(page);
      const fixed = "2026-10-26T12:00:00Z";
      const conversation = {
        id: "ui-test-conversation",
        course_id: "machine-learning",
        title: "测试课程讨论",
        selected_mode: "coach",
        requested_profile_id: "test-profile",
        experience_mode: "manual",
        version: 1,
        preview: "",
        message_count: 0,
        created_at: fixed,
        updated_at: fixed,
        messages: [],
      };
      const memory = {
        id: "ui-test-memory",
        course_id: "machine-learning",
        memory_kind: "explanation_preference",
        content: "先核对使用条件",
        confidence: 0.8,
        status: "active",
        source_count: 1,
      };
      await page.route("**/api/v1/model-profiles?*", (route) =>
        route.fulfill({
          json: [
            {
              id: "test-profile",
              display_name: "课程辅导模型",
              available: true,
              unavailable_reason: null,
              task_kinds: [],
              capabilities: [],
              config_revision: "1",
            },
          ],
        }),
      );
      await page.route(
        "**/api/v1/student/courses/*/tutor/conversations",
        (route) => route.fulfill({ json: [conversation] }),
      );
      await page.route(
        "**/api/v1/student/courses/*/tutor/conversations/ui-test-conversation",
        (route) =>
          route.request().method() === "GET"
            ? route.fulfill({ json: conversation })
            : route.fulfill({
                status: 409,
                json: { detail: "保存失败，请重新读取对话。" },
              }),
      );
      await page.route("**/api/v1/student/courses/*/tutor/memories", (route) =>
        route.fulfill({ json: [memory] }),
      );
      await page.route(
        "**/api/v1/student/courses/*/tutor/memories/*:resolve",
        (route) =>
          route.fulfill({
            status: 503,
            json: { detail: "记忆暂时无法保存。" },
          }),
      );
      const sent = [];
      let failMode = "json";
      await page.route(
        "**/api/v1/student/courses/*/tutor/conversations/*/turns",
        async (route) => {
          sent.push(route.request().postDataJSON());
          if (failMode === "network") await route.abort("failed");
          else
            await route.fulfill({
              status: 503,
              json: { detail: "辅导服务暂不可用，请稍后重试。" },
            });
        },
      );
      await page.goto(base + "/student/tutor");
      await ready(page);
      const input = page.locator("#tutor-message");
      await input.fill("损失函数与评价指标有什么区别？");
      await input.dispatchEvent("keydown", {
        key: "Enter",
        code: "Enter",
        isComposing: true,
      });
      await page.waitForTimeout(100);
      check("中文输入法确认键不发送提问", sent.length === 0, "ui_fixture");
      await input.press("Shift+Enter");
      check(
        "Shift+Enter保留换行",
        (await input.inputValue()).includes("\n"),
        "ui_fixture",
      );
      await page
        .locator("input[type=file]")
        .setInputFiles({
          name: "课程说明.txt",
          mimeType: "text/plain",
          buffer: Buffer.from("损失函数衡量预测值与目标值的差异。"),
        });
      await ready(page);
      await page.getByRole("button", { name: "发送问题", exact: true }).click();
      await ready(page);
      check(
        "发送失败保留问题与附件",
        (await input.inputValue()).includes("评价指标") &&
          (await page.locator(".attachment-chips").isVisible()),
        "ui_fixture",
      );
      failMode = "network";
      await page.getByRole("button", { name: "发送问题", exact: true }).click();
      await ready(page);
      check(
        "结果未确认时阻止盲目重发",
        await page
          .getByRole("button", { name: "发送问题", exact: true })
          .isDisabled(),
        "ui_fixture",
      );
      await page.getByRole("button", { name: "核对对话记录" }).click();
      await ready(page);
      await page.getByRole("button", { name: "发送问题", exact: true }).click();
      await ready(page);
      check(
        "核对后重试沿用完整请求内容与幂等标识",
        JSON.stringify(sent[1]) === JSON.stringify(sent[2]),
        "ui_fixture",
      );
      await page.getByRole("button", { name: "核对对话记录" }).click();
      await ready(page);
      await page
        .getByRole("button", { name: "重命名测试课程讨论", exact: true })
        .click();
      check(
        "会话管理使用可聚焦弹窗",
        await page.locator("[role=dialog]").isVisible(),
        "ui_fixture",
      );
      await page.locator("[role=dialog] input").fill("新的名称");
      await page
        .locator("[role=dialog] form")
        .evaluate((el) => el.requestSubmit());
      await ready(page);
      check(
        "重命名失败保留原会话",
        await page
          .getByRole("button", { name: "重命名测试课程讨论", exact: true })
          .isVisible(),
        "ui_fixture",
      );
      await page
        .getByRole("button", { name: "删除测试课程讨论", exact: true })
        .click();
      await page.keyboard.press("Escape");
      check(
        "Esc关闭管理弹窗并恢复焦点",
        (await page.locator("[role=dialog]").count()) === 0 &&
          (await page.evaluate(
            () =>
              document.activeElement?.getAttribute("aria-label") ===
              "删除测试课程讨论",
          )),
        "ui_fixture",
      );
      await page.getByRole("button", { name: "学习记忆", exact: true }).click();
      await ready(page);
      await page.getByRole("button", { name: "替换", exact: true }).click();
      await page.locator("[role=dialog] input").fill("先列出概念的输入输出");
      await page
        .locator("[role=dialog] form")
        .evaluate((el) => el.requestSubmit());
      await ready(page);
      check(
        "记忆替换失败保留原内容并反馈",
        (await page.locator(".tutor-library").innerText()).includes(
          "先核对使用条件",
        ) &&
          (await page.locator(".inline-error").innerText()).includes(
            "暂时无法保存",
          ),
        "ui_fixture",
      );
    });
    check("浏览器无未处理异常", errors.length === 0, "browser");
    completed = true;
  } finally {
    await browser.close();
    const result = {
      checks,
      pageErrors: errors,
      pass: completed && !errors.length,
    };
    if (process.env.ZHIXUE_QA_OUTPUT) {
      fs.mkdirSync(process.env.ZHIXUE_QA_OUTPUT, { recursive: true });
      fs.writeFileSync(
        path.join(process.env.ZHIXUE_QA_OUTPUT, "browser-regression.json"),
        JSON.stringify(result, null, 2),
      );
    }
    console.log(JSON.stringify(result, null, 2));
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
