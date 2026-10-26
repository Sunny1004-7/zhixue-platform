const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

async function verifyNavigation(
  browser,
  {
    baseUrl = "http://127.0.0.1:5173",
    route = (x) => x,
    outputDir,
    prefix = "app",
    backend = true,
  } = {},
) {
  const checks = [],
    errors = [];
  let snapshotPosts = 0,
    watchSnapshots = false;
  const check = (name, value) => {
    assert.ok(value, name);
    checks.push({ name, pass: true });
  };
  if (outputDir) fs.mkdirSync(outputDir, { recursive: true });
  async function ready(page) {
    await page.waitForLoadState("networkidle");
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(250);
  }
  async function login(page, role) {
    await page.goto(baseUrl + route("/login"));
    await page
      .locator("label.zx-role")
      .filter({ has: page.locator(`input[value=${role}]`) })
      .click();
    await page
      .getByLabel(role === "student" ? "学生账号" : "教师账号", { exact: true })
      .fill(role + "@zhixing.edu.cn");
    await page.getByLabel("登录密码", { exact: true }).fill("zhixing2026");
    await page
      .getByRole("button", {
        name: role === "student" ? "进入学生空间" : "进入教师空间",
        exact: true,
      })
      .click();
    await ready(page);
  }
  async function shot(page, name) {
    if (outputDir)
      await page.screenshot({
        path: path.join(outputDir, prefix + "-" + name + ".png"),
        fullPage: page.viewportSize().width === 390,
      });
  }
  for (const size of [
    [2560, 1440],
    [1366, 768],
    [390, 844],
  ])
    for (const role of ["student", "teacher"]) {
      const ctx = await browser.newContext({
          viewport: { width: size[0], height: size[1] },
          deviceScaleFactor: 1,
          locale: "zh-CN",
          reducedMotion: "reduce",
        }),
        page = await ctx.newPage();
      page.on("pageerror", (e) => errors.push(e.message));
      try {
        await login(page, role);
        await page.goto(
          baseUrl + route("/" + role + "/overview?view=learning"),
        );
        await ready(page);
        const original = page.url(),
          course = await page.evaluate(() =>
            sessionStorage.getItem("zhixing-course-id"),
          );
        await page
          .getByRole("link", { name: "跳转到主要内容", exact: true })
          .focus();
        await page.keyboard.press("Enter");
        check(
          `${size[0]}/${role}: skip keeps route, query and course`,
          page.url() === original &&
            (await page.evaluate(
              () =>
                document.activeElement?.id === "main-content" &&
                sessionStorage.getItem("zhixing-course-id"),
            )) === course,
        );
        const sidebar = page.locator(".sidebar");
        if (size[0] === 390) {
          check(
            `${role}: closed drawer inert and hidden`,
            await sidebar.evaluate(
              (el) => el.inert && el.getAttribute("aria-hidden") === "true",
            ),
          );
          await page
            .getByRole("link", { name: "跳转到主要内容", exact: true })
            .focus();
          for (let i = 0; i < 18; i++) {
            await page.keyboard.press("Tab");
            check(
              `${role}: closed drawer absent from Tab ${i}`,
              await page.evaluate(
                () => !document.activeElement?.closest(".sidebar"),
              ),
            );
          }
          await shot(page, role + "-mobile-closed");
          await page
            .getByRole("button", { name: "打开导航", exact: true })
            .click();
          await page.waitForFunction(() =>
            document.activeElement?.closest(".sidebar"),
          );
          check(
            `${role}: open drawer focus enters`,
            await sidebar.evaluate(
              (el) => !el.inert && el.getAttribute("aria-modal") === "true",
            ),
          );
          await shot(page, role + "-mobile-open");
          await page.keyboard.press("Escape");
          await page.waitForFunction(
            () =>
              document.activeElement?.getAttribute("aria-label") === "打开导航",
          );
          check(`${role}: Escape returns focus`, true);
          await page.setViewportSize({ width: 1366, height: 768 });
          await page.waitForTimeout(250);
          check(
            `${role}: desktop after resize enabled`,
            await sidebar.evaluate(
              (el) => !el.inert && !el.hasAttribute("aria-hidden"),
            ),
          );
          await sidebar.getByLabel("当前课程", { exact: true }).focus();
          check(
            `${role}: desktop sidebar focusable`,
            await page.evaluate(
              () => !!document.activeElement?.closest(".sidebar"),
            ),
          );
          await page.setViewportSize({ width: 390, height: 844 });
          await page.waitForTimeout(250);
          check(
            `${role}: mobile after resize inert`,
            await sidebar.evaluate((el) => el.inert),
          );
        } else
          check(
            `${size[0]}/${role}: desktop sidebar enabled`,
            await sidebar.evaluate((el) => !el.inert),
          );
        check(
          `${size[0]}/${role}: stable page width`,
          await page.evaluate(
            () => document.documentElement.scrollWidth === innerWidth,
          ),
        );
        if (size[0] === 2560) await shot(page, role + "-main-focused-2k");
      } catch (error) {
        await shot(page, `${role}-${size[0]}-failure`);
        if (outputDir) fs.writeFileSync(path.join(outputDir, prefix+"-failure.json"), JSON.stringify({url:page.url(),role,viewport:size,body:(await page.locator('body').innerText()).slice(0,6000),pageErrors:errors},null,2));
        throw error;
      } finally {
        await ctx.close();
      }
    }
  const ctx = await browser.newContext({
      viewport: { width: 2560, height: 1440 },
      deviceScaleFactor: 1,
      locale: "zh-CN",
    }),
    page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("request", (r) => {
    if (
      watchSnapshots &&
      r.method() === "POST" &&
      r.url().includes("/decision-snapshots:refresh")
    )
      snapshotPosts++;
  });
  try {
    await login(page, "teacher");
    await page.goto(baseUrl + route("/teacher/students"));
    await ready(page);
    watchSnapshots = true;
    const input = page.getByRole("textbox", { name: "搜索学生", exact: true });
    await input.focus();
    for (const character of ["林", "知", "夏"]) {
      await page.keyboard.insertText(character);
      await ready(page);
      check(
        "continuous typing focus " + character,
        await input.evaluate((el) => el === document.activeElement),
      );
    }
    check("continuous Chinese value", (await input.inputValue()) === "林知夏");
    await input.fill("");
    await ready(page);
    check(
      "clear keeps focus",
      await input.evaluate((el) => el === document.activeElement),
    );
    await input.dispatchEvent("compositionstart");
    await page.keyboard.insertText("林");
    await page.waitForTimeout(250);
    check(
      "composition preserves field",
      await input.evaluate((el) => el === document.activeElement),
    );
    await input.dispatchEvent("compositionend");
    await ready(page);
    await input.fill("林知");
    await input.fill("不存在的学生");
    await ready(page);
    check(
      "empty search state",
      await page.getByText("当前筛选没有学生", { exact: true }).isVisible(),
    );
    await input.fill("");
    await ready(page);
    for (const name of ["关注得分降序", "姓名排序", "关注得分升序"]) {
      await page.getByRole("button", { name, exact: true }).click();
      await ready(page);
    }
    if (backend) {
      await page.route("**/api/v1/courses/*/students?*", (r) =>
        r.abort("failed"),
      );
      await input.fill("林");
      await ready(page);
      check(
        "search failure keeps input mounted",
        (await input.inputValue()) === "林",
      );
      await input.focus();
      check(
        "search failure field focusable",
        await input.evaluate((el) => el === document.activeElement),
      );
      await page.unroute("**/api/v1/courses/*/students?*");
      await page.locator(".student-roster-panel .error-state button").click();
      await ready(page);
      check(
        "search retry succeeds",
        (await page.locator(".student-roster-panel .error-state").count()) ===
          0,
      );
    }
    check("search and sort create no snapshot", snapshotPosts === 0);
    const filterSnapshotPosts = snapshotPosts;
    await shot(page, "teacher-search-2k");
    await page.getByRole("button", { name: "刷新快照", exact: true }).click();
    await ready(page);
    if (backend)
      check(
        "explicit refresh creates exactly one snapshot",
        snapshotPosts === 1,
      );
    await page
      .locator(".sidebar")
      .getByLabel("当前课程", { exact: true })
      .selectOption("ai-intro");
    await ready(page);
    check(
      "course change restores own list",
      (await page
        .locator(".sidebar")
        .getByLabel("当前课程", { exact: true })
        .inputValue()) === "ai-intro",
    );
    check("no page exceptions", !errors.length);
    return {
      checks,
      pageErrors: errors,
      filterSnapshotPosts: backend ? filterSnapshotPosts : null,
      pass: true,
    };
  } finally {
    await ctx.close();
  }
}
module.exports = { verifyNavigation };
if (require.main === module)
  (async () => {
    const browser = await chromium.launch({
      channel: process.env.PLAYWRIGHT_CHANNEL || "msedge",
      headless: true,
    });
    try {
      const outputDir =
        process.env.ZHIXUE_QA_OUTPUT ||
        path.resolve(__dirname, "../.qa-artifacts/navigation");
      const report = await verifyNavigation(browser, { outputDir });
      fs.writeFileSync(
        path.join(outputDir, "navigation-checks.json"),
        JSON.stringify(report, null, 2),
      );
      console.log(report.checks.length + " navigation checks passed");
    } finally {
      await browser.close();
    }
  })().catch((e) => {
    console.error(e);
    process.exitCode = 1;
  });
