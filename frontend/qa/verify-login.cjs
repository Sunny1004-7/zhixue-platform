const path = require("path");
const fs = require("fs");
const assert = require("node:assert/strict");
const { chromium } = require("playwright");
const { launchBrowser } = require("./browser.cjs");

/** Reusable browser checks; callers supply URLs and artifact paths, never auth results. */
async function verifyLogin(
  browser,
  {
    baseUrl,
    route = (x) => x,
    outputDir,
    prefix = "real",
    backend = true,
    apiBase = process.env.ZHIXING_API_BASE || "http://127.0.0.1:8000/api/v1",
  },
) {
  fs.mkdirSync(outputDir, { recursive: true });
  const report = {
    project: prefix,
    checks: [],
    requestCount: 0,
    pageErrors: [],
    networkFailures: [],
  };
  const check = (name, actual, detail) => {
    assert.ok(actual, `${prefix}: ${name}`);
    report.checks.push({ name, pass: true, detail });
  };
  const context = await browser.newContext({
    viewport: { width: 2560, height: 1440 },
    deviceScaleFactor: 1,
    locale: "zh-CN",
    timezoneId: "Asia/Shanghai",
    reducedMotion: "reduce",
  });
  const page = await context.newPage();
  page.on("pageerror", (error) => report.pageErrors.push(error.message));
  page.on("request", (request) => {
    if (["fetch", "xhr"].includes(request.resourceType()))
      report.requestCount++;
  });
  const go = async (url) => {
    await page.goto(baseUrl + route(url));
    await page.waitForLoadState("networkidle");
  };
  const cleanShot = async (name) => {
    await page.mouse.move(0, 0);
    await page.screenshot({
      path: path.join(outputDir, `${prefix}-${name}.png`),
      fullPage: false,
    });
  };
  try {
    for (const role of ["student", "teacher"]) {
      const label = role === "student" ? "学生" : "教师";
      await go("/login");
      await page.locator(".zx-submit:not(:disabled)").waitFor();
      await page.locator(".zx-role").filter({ hasText: label }).click();
      check(
        `${role}:initial-empty-fields`,
        (await page
          .getByLabel(`${label}账号`, { exact: true })
          .inputValue()) === "" &&
          (await page.getByLabel("登录密码", { exact: true }).inputValue()) ===
            "",
      );
      await page.getByLabel(`${label}账号`, { exact: true }).focus();
      await cleanShot(`${role}-focus-2560x1440`);
      await page.getByRole("button", { name: `进入${label}空间` }).click();
      check(
        `${role}:required-validation`,
        (await page.locator('[aria-invalid="true"]').count()) === 2,
      );
      check(
        `${role}:first-error-focus`,
        await page
          .getByLabel(`${label}账号`, { exact: true })
          .evaluate((e) => e === document.activeElement),
      );
      await cleanShot(`${role}-validation-2560x1440`);
      await page
        .getByLabel(`${label}账号`, { exact: true })
        .fill(`${role}@zhixing.edu.cn`);
      await page.getByRole("button", { name: `进入${label}空间` }).click();
      check(
        `${role}:password-error-focus`,
        await page
          .getByLabel("登录密码", { exact: true })
          .evaluate((e) => e === document.activeElement),
      );
      await page
        .getByLabel("登录密码", { exact: true })
        .fill("incorrect-password");
      await page.getByRole("button", { name: "显示密码", exact: true }).click();
      check(
        `${role}:password-visible`,
        (await page
          .getByLabel("登录密码", { exact: true })
          .getAttribute("type")) === "text",
      );
      await page.getByRole("button", { name: "隐藏密码", exact: true }).click();
      check(
        `${role}:password-hidden`,
        (await page
          .getByLabel("登录密码", { exact: true })
          .getAttribute("type")) === "password",
      );
      await page.getByRole("button", { name: `进入${label}空间` }).click();
      await page.getByRole("alert").waitFor();
      await page.waitForFunction(() => document.querySelector('[role="alert"]') === document.activeElement);
      check(
        `${role}:wrong-credentials`,
        (await page.getByRole("alert").textContent()).includes("不匹配"),
      );
      check(
        `${role}:error-focus`,
        await page
          .getByRole("alert")
          .evaluate((e) => e === document.activeElement),
      );
      await cleanShot(`${role}-credential-error-2560x1440`);
      await page.getByLabel("登录密码", { exact: true }).fill("zhixing2026");
      // Delay transport only to make the transient submitting state observable.
      if (backend)
        await page.route("**/api/v1/auth/login", async (route) => {
          await new Promise((resolve) => setTimeout(resolve, 650));
          await route.continue();
        });
      await page.getByRole("button", { name: `进入${label}空间` }).click();
      await page
        .getByRole("button", { name: "正在验证身份…", exact: true })
        .waitFor();
      const disabledControls = await page
        .locator(".zx-form")
        .evaluate((form) => ({
          submit: form.querySelector(".zx-submit").disabled,
          password: form.querySelector('[name="password"]').disabled,
          roles: form.querySelector(".zx-roles").disabled,
        }));
      check(
        `${role}:submitting-controls-disabled`,
        Object.values(disabledControls).every(Boolean),
        disabledControls,
      );
      check(
        `${role}:aria-busy`,
        (await page.locator(".zx-form").getAttribute("aria-busy")) === "true",
      );
      await cleanShot(`${role}-submitting-2560x1440`);
      const destination =
        role === "student" ? "/student/courses" : "/teacher/overview";
      await page.waitForURL((url) =>
        (url.hash || url.pathname).includes(destination),
      );
      await page.waitForLoadState("networkidle");
      check(`${role}:successful-login`, true, destination);
      if (backend) await page.unroute("**/api/v1/auth/login");
      await page.reload();
      await page.waitForLoadState("networkidle");
      check(`${role}:session-restore`, page.url().includes(destination));
      const foreign =
        role === "student" ? "/teacher/overview" : "/student/courses";
      await go(foreign);
      await page.waitForURL((url) =>
        (url.hash || url.pathname).includes(destination),
      );
      check(`${role}:wrong-role-route`, !page.url().includes(foreign));
      let token;
      if (backend) {
        token = await page.evaluate(() =>
          sessionStorage.getItem("zhixing-access-token"),
        );
        const courses = await context.request.get(`${apiBase}/courses`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        const courseId = (await courses.json())[0].id;
        const deniedPath =
          role === "student"
            ? `/teacher/courses/${courseId}/overview`
            : `/student/courses/${courseId}/overview`;
        const denied = await context.request.get(apiBase + deniedPath, {
          headers: { Authorization: `Bearer ${token}` },
        });
        check(`${role}:backend-role-permission`, denied.status() === 403, {
          status: denied.status(),
        });
      }
      await page.getByRole("button", { name: /^退出(当前账号)?$/ }).click();
      await page.waitForURL((url) =>
        (url.hash || url.pathname).includes("/login"),
      );
      check(`${role}:logout`, true);
      if (backend) {
        const expired = await context.request.get(`${apiBase}/me`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        check(`${role}:logout-invalidates-token`, expired.status() === 401, {
          status: expired.status(),
        });
      }
      await go(destination);
      await page.waitForURL((url) =>
        (url.hash || url.pathname).includes("/login"),
      );
      check(`${role}:unauthenticated-route`, true);
    }
    await go("/login");
    await page.getByRole("radio", { name: "学生", exact: true }).focus();
    await page.keyboard.press("ArrowRight");
    check(
      "keyboard-role-selection",
      await page.getByRole("radio", { name: "教师", exact: true }).isChecked(),
    );
    await page.keyboard.press("ArrowLeft");
    check(
      "keyboard-role-selection-back",
      await page.getByRole("radio", { name: "学生", exact: true }).isChecked(),
    );
    await page.getByRole("link", { name: "跳到登录表单" }).focus();
    await page.keyboard.press("Enter");
    check(
      "keyboard-skip-link",
      (await page
        .locator(".zx-form")
        .evaluate((e) => e === document.activeElement)) &&
        page.url().includes("/login"),
    );
    await page.keyboard.press("Tab");
    check(
      "keyboard-tab-enters-form",
      await page
        .getByRole("radio", { name: "学生", exact: true })
        .evaluate((e) => e === document.activeElement),
    );
    await page
      .getByLabel("学生账号", { exact: true })
      .fill("student@zhixing.edu.cn");
    await page.getByLabel("登录密码", { exact: true }).fill("zhixing2026");
    await page.getByLabel("登录密码", { exact: true }).press("Enter");
    await page.waitForURL((url) =>
      (url.hash || url.pathname).includes("/student/courses"),
    );
    check("keyboard-enter-submits", true);
    await page.getByRole("button", { name: /^退出$/ }).click();
    await page.waitForURL((url) =>
      (url.hash || url.pathname).includes("/login"),
    );
    if (backend) {
      await page
        .getByLabel("学生账号", { exact: true })
        .fill("student@zhixing.edu.cn");
      await page.getByLabel("登录密码", { exact: true }).fill("zhixing2026");
      await page.route("**/api/v1/auth/login", (route) =>
        route.abort("failed"),
      );
      await page.getByRole("button", { name: "进入学生空间" }).click();
      await page.getByRole("alert").waitFor();
      check(
        "network-failure-visible",
        (await page.getByRole("alert").textContent()).includes(
          "无法连接登录服务",
        ),
      );
      check(
        "network-failure-no-session",
        await page.evaluate(
          () => sessionStorage.getItem("zhixing-access-token") === null,
        ),
      );
      await page.unroute("**/api/v1/auth/login");
    }
    check("no-runtime-exceptions", report.pageErrors.length === 0);
    if (!backend) check("offline-no-fetch-xhr", report.requestCount === 0);
    return report;
  } finally {
    await context.close();
  }
}

module.exports = { verifyLogin };
if (require.main === module) {
  (async () => {
    const browser = await launchBrowser(chromium);
    try {
      const outputDir =
        process.env.ZHIXING_QA_OUTPUT_DIR ||
        path.resolve(__dirname, "..", ".qa-artifacts", "login");
      const result = await verifyLogin(browser, {
        baseUrl: process.env.ZHIXING_FRONTEND_URL || "http://127.0.0.1:5173",
        outputDir,
      });
      fs.writeFileSync(
        path.join(outputDir, "login-checks.json"),
        JSON.stringify(result, null, 2),
      );
      console.log(`${result.checks.length} login checks passed`);
    } finally {
      await browser.close();
    }
  })().catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
}
