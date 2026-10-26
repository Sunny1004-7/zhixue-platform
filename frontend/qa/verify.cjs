const path = require("path");
const { chromium } = require(
  process.env.PLAYWRIGHT_MODULE_PATH || "playwright",
);
const { launchBrowser } = require("./browser.cjs");

const baseUrl = process.env.ZHIXING_FRONTEND_URL || "http://127.0.0.1:5173";
const outputDir = path.resolve(
  process.env.ZHIXING_QA_OUTPUT_DIR ||
    path.join(__dirname, "..", ".qa-artifacts"),
);
require("fs").mkdirSync(outputDir, { recursive: true });

async function inspect(page, name) {
  await page.waitForLoadState("networkidle");
  const state = await page.evaluate(() => ({
    path: location.pathname,
    title: document.querySelector("h1, h2")?.textContent?.trim() ?? "",
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
    emptyButtons: [...document.querySelectorAll("button")].filter(
      (item) => !item.textContent?.trim() && !item.getAttribute("aria-label"),
    ).length,
  }));
  if (state.scrollWidth > state.clientWidth)
    throw new Error(
      `${name} 出现横向溢出：${state.scrollWidth}/${state.clientWidth}`,
    );
  if (state.emptyButtons)
    throw new Error(`${name} 存在 ${state.emptyButtons} 个无名称按钮`);
  await page.screenshot({
    path: path.join(outputDir, `${name}.png`),
    fullPage: false,
  });
  return state;
}

(async () => {
  const browser = await launchBrowser(chromium);
  const report = [];
  try {
    const student = await browser.newPage({
      viewport: { width: 1440, height: 900 },
    });
    const studentErrors = [];
    student.on("console", (message) => {
      if (message.type() === "error") studentErrors.push(message.text());
    });
    student.on("requestfailed", (request) =>
      studentErrors.push(`${request.url()}: ${request.failure()?.errorText}`),
    );
    student.on("response", (response) => {
      if (response.status() >= 400)
        studentErrors.push(`${response.status()} ${response.url()}`);
    });
    await student.goto(`${baseUrl}/login`);
    report.push(await inspect(student, "login-student"));
    await student
      .getByLabel("学生账号", { exact: true })
      .fill("student@zhixing.edu.cn");
    await student.getByLabel("登录密码", { exact: true }).fill("zhixing2026");
    await student.getByRole("button", { name: /进入学生空间/ }).click();
    await student.waitForURL("**/student/courses");
    await student.locator(".course-grid .course-card").first().waitFor();
    report.push(await inspect(student, "student-courses"));
    await student
      .getByRole("button", { name: /进入课程/ })
      .first()
      .click();
    await student.waitForURL("**/student/overview");
    await student.locator(".page-intro").waitFor();
    report.push(await inspect(student, "student-overview"));
    await student
      .getByRole("button", { name: "查看全部", exact: true })
      .first()
      .click();
    const masteryDialog = student.getByRole("dialog", {
      name: "完整知识掌握状态",
    });
    await masteryDialog.waitFor();
    const masteryRows = masteryDialog.locator("tbody tr");
    const masteryCount = await masteryRows.count();
    if (masteryCount !== 10)
      throw new Error(`完整知识状态应包含10个知识点，实际为${masteryCount}个`);
    report.push(await inspect(student, "student-mastery"));
    await masteryDialog.getByRole("button", { name: "关闭" }).click();
    await masteryDialog.waitFor({ state: "hidden" });
    await student.getByRole("link", { name: "学习资源" }).click();
    await student.waitForURL("**/student/resources");
    const graphCards = student.locator(".graph-card-grid article");
    await graphCards.first().waitFor();
    if ((await graphCards.count()) !== 2)
      throw new Error("机器学习课程应展示2份已发布知识图谱");
    report.push(await inspect(student, "student-resources"));
    await graphCards
      .first()
      .getByRole("button", { name: /进入图谱/ })
      .click();
    const graphDialog = student.getByRole("dialog");
    await graphDialog.waitFor();
    if ((await graphDialog.locator(".graph-node").count()) !== 11)
      throw new Error("学生图谱应展示11个知识点");
    if ((await graphDialog.locator(".graph-edge").count()) !== 14)
      throw new Error("学生图谱应展示14条关系");
    await graphDialog.locator(".graph-node").first().click();
    await graphDialog.locator(".knowledge-card").waitFor();
    report.push(await inspect(student, "student-graph-card"));
    await graphDialog.getByRole("button", { name: "全屏查看" }).click();
    if (
      !(await graphDialog.evaluate((element) =>
        element.classList.contains("expanded"),
      ))
    )
      throw new Error("图谱全屏状态未生效");
    report.push(await inspect(student, "student-graph-expanded"));
    await graphDialog.getByRole("button", { name: "退出全屏" }).click();
    await graphDialog
      .getByRole("button", { name: "关闭", exact: true })
      .click();
    if (studentErrors.length)
      throw new Error(`学生端控制台/网络错误：${studentErrors.join(" | ")}`);

    const teacher = await browser.newPage({
      viewport: { width: 1440, height: 900 },
    });
    const teacherErrors = [];
    teacher.on("console", (message) => {
      if (message.type() === "error") teacherErrors.push(message.text());
    });
    teacher.on("requestfailed", (request) =>
      teacherErrors.push(`${request.url()}: ${request.failure()?.errorText}`),
    );
    teacher.on("response", (response) => {
      if (response.status() >= 400)
        teacherErrors.push(`${response.status()} ${response.url()}`);
    });
    await teacher.goto(`${baseUrl}/login`);
    await teacher.locator(".zx-role").filter({ hasText: "教师" }).click();
    await teacher
      .getByLabel("教师账号", { exact: true })
      .fill("teacher@zhixing.edu.cn");
    await teacher.getByLabel("登录密码", { exact: true }).fill("zhixing2026");
    report.push(await inspect(teacher, "login-teacher"));
    await teacher.getByRole("button", { name: /进入教师空间/ }).click();
    await teacher.waitForURL("**/teacher/overview");
    await teacher.locator(".page-intro").waitFor();
    report.push(await inspect(teacher, "teacher-overview"));
    await teacher.getByRole("link", { name: "知识图谱构建" }).click();
    await teacher.waitForURL("**/teacher/graphs");
    const teacherGraphs = teacher.locator(".teacher-graph-list > button");
    await teacherGraphs.first().waitFor();
    if ((await teacherGraphs.count()) !== 2)
      throw new Error("教师端机器学习课程应展示2份图谱");
    await teacherGraphs.first().click();
    await teacher.locator(".teacher-graph-workspace .graph-view").waitFor();
    report.push(await inspect(teacher, "teacher-graphs"));
    const updateGraph = teacher.getByRole("button", {
      name: "更新图谱",
      exact: true,
    });
    if (await updateGraph.isVisible()) {
      await updateGraph.click();
      await teacher
        .getByRole("button", { name: "导入教学材料", exact: true })
        .waitFor();
    }
    await teacher
      .getByRole("button", { name: "编辑图谱", exact: true })
      .click();
    const editorDialog = teacher.getByRole("dialog", { name: "编辑知识图谱" });
    await editorDialog.waitFor();
    if (
      (await editorDialog
        .locator(".graph-editor-list > div > button")
        .count()) !== 11
    ) {
      throw new Error("教师图谱编辑器应列出当前修订的11个知识点");
    }
    await editorDialog.locator(".graph-evidence-panel").waitFor();
    await editorDialog
      .getByLabel("教师来源说明（可选）")
      .fill("课程初始图谱内容，教师已复核。");
    await Promise.all([
      teacher.waitForResponse(
        (response) =>
          response.request().method() === "PATCH" &&
          response.url().includes("/nodes/") &&
          response.status() === 200,
      ),
      editorDialog
        .getByRole("button", { name: "保存知识点", exact: true })
        .click(),
    ]);
    await editorDialog.getByRole("button", { name: /知识关系/ }).click();
    if (
      (await editorDialog
        .locator(".graph-editor-list > div > button")
        .count()) !== 14
    ) {
      throw new Error("教师图谱编辑器应列出当前修订的14条关系");
    }
    report.push(await inspect(teacher, "teacher-graph-editor"));
    await editorDialog.getByRole("button", { name: "关闭图谱编辑器" }).click();
    await editorDialog.waitFor({ state: "hidden" });
    await teacher
      .getByRole("button", { name: "AI语义预审", exact: true })
      .click();
    const semanticDialog = teacher.getByRole("dialog", { name: "AI语义预审" });
    await semanticDialog.waitFor();
    await semanticDialog.locator(".semantic-review-boundary").waitFor();
    const semanticOptions = semanticDialog.locator(
      ".semantic-review-setup option",
    );
    await semanticDialog.locator(".semantic-review-setup select").waitFor();
    await teacher.waitForFunction(
      () =>
        document.querySelectorAll(
          ".semantic-review-dialog .semantic-review-setup option",
        ).length >= 4,
    );
    if ((await semanticOptions.count()) !== 4)
      throw new Error("语义预审必须展示4个模型Profile");
    const semanticButton = semanticDialog.getByRole("button", {
      name: "开始语义预审",
      exact: true,
    });
    if (await semanticButton.isEnabled())
      throw new Error("未配置模型凭证时，语义预审启动按钮必须明确不可用");
    report.push(await inspect(teacher, "teacher-semantic-review-unavailable"));
    await semanticDialog
      .getByRole("button", { name: "完成", exact: true })
      .click();
    await semanticDialog.waitFor({ state: "hidden" });
    await teacher
      .getByRole("button", { name: "导入教学材料", exact: true })
      .click();
    const sourceDialog = teacher.getByRole("dialog", { name: "导入教学材料" });
    await sourceDialog.waitFor();
    await sourceDialog
      .getByRole("button", { name: "输入自然语言", exact: true })
      .click();
    await sourceDialog.locator("textarea").fill("线性回归；损失函数；量子引力");
    await sourceDialog
      .getByRole("button", { name: "开始识别与对齐", exact: true })
      .click();
    const alignmentRows = sourceDialog.locator(".alignment-row");
    await alignmentRows.first().waitFor();
    if ((await alignmentRows.count()) !== 3)
      throw new Error("自然语言输入应按顺序得到3条知识点对齐结果");
    const abstainButton = sourceDialog.getByRole("button", {
      name: "暂不纳入",
      exact: true,
    });
    await abstainButton.click();
    await abstainButton.waitFor({ state: "hidden" });
    report.push(await inspect(teacher, "teacher-material-alignment"));
    const modelOptions = sourceDialog.locator(".model-extraction-setup option");
    if ((await modelOptions.count()) !== 4)
      throw new Error("图谱抽取必须展示4个模型Profile");
    await sourceDialog
      .getByRole("button", { name: "仅加入知识点", exact: true })
      .click();
    await sourceDialog.waitFor({ state: "hidden" });
    await teacher
      .getByRole("button", { name: "导入教学材料", exact: true })
      .click();
    await sourceDialog.waitFor();
    await sourceDialog.locator('input[type="file"]').setInputFiles({
      name: "线性回归课堂讲义.txt",
      mimeType: "text/plain",
      buffer: Buffer.from(
        "线性回归用于描述输入与输出的线性关系。\n\n损失函数衡量预测误差。",
        "utf8",
      ),
    });
    await sourceDialog
      .getByRole("button", { name: "开始识别与对齐", exact: true })
      .click();
    await sourceDialog.locator(".alignment-row").first().waitFor();
    if ((await sourceDialog.locator(".alignment-row").count()) !== 2)
      throw new Error("教学文件应识别出2个课程知识点");
    const extractButton = sourceDialog.getByRole("button", {
      name: "提取知识结构",
      exact: true,
    });
    if (await extractButton.isEnabled())
      throw new Error("未配置模型凭证时，结构抽取按钮必须明确不可用");
    report.push(await inspect(teacher, "teacher-material-file-alignment"));
    await sourceDialog
      .getByRole("button", { name: "关闭", exact: true })
      .click();
    await sourceDialog.waitFor({ state: "hidden" });
    if (teacherErrors.length)
      throw new Error(`教师端控制台/网络错误：${teacherErrors.join(" | ")}`);

    process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
  } finally {
    await browser.close();
  }
})().catch((error) => {
  process.stderr.write(`${error.stack ?? error}\n`);
  process.exitCode = 1;
});
