const path = require('path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const { launchBrowser } = require('./browser.cjs');

const baseUrl = process.env.A3_BASE_URL || 'http://127.0.0.1:4174';
const outputDir = path.resolve(process.env.ZHIXING_QA_OUTPUT_DIR || path.join(__dirname, '..', '.qa-artifacts'));
require('fs').mkdirSync(outputDir, { recursive: true });

async function inspect(page, name) {
  await page.waitForLoadState('networkidle');
  const state = await page.evaluate(() => ({
    path: location.pathname,
    title: document.querySelector('h1, h2')?.textContent?.trim() || '',
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
    emptyButtons: [...document.querySelectorAll('button')]
      .filter((item) => !item.textContent?.trim() && !item.getAttribute('aria-label') && !item.getAttribute('title'))
      .length,
  }));
  if (state.scrollWidth > state.clientWidth) throw new Error(`${name} 出现横向溢出：${state.scrollWidth}/${state.clientWidth}`);
  if (state.emptyButtons) throw new Error(`${name} 存在 ${state.emptyButtons} 个无名称按钮`);
  await page.screenshot({ path: path.join(outputDir, `${name}.png`), fullPage: false });
  return state;
}

function trackErrors(page) {
  const errors = [];
  page.on('console', (message) => { if (message.type() === 'error') errors.push(message.text()); });
  page.on('requestfailed', (request) => errors.push(`${request.url()}: ${request.failure()?.errorText}`));
  page.on('response', (response) => { if (response.status() >= 400) errors.push(`${response.status()} ${response.url()}`); });
  return errors;
}

async function login(page, role) {
  await page.goto(`${baseUrl}/login`);
  if (role === 'teacher') await page.locator('.zx-role').filter({ hasText: '教师' }).click();
  await page.locator('input[autocomplete="username"]').fill(role === 'teacher'
    ? 'teacher@zhixing.edu.cn'
    : 'student@zhixing.edu.cn');
  await page.locator('input[autocomplete="current-password"]').fill('zhixing2026');
  await page.locator('.zx-submit').click();
  await page.waitForURL(role === 'teacher' ? '**/teacher/overview' : '**/student/courses');
  if (role === 'student') {
    await page.locator('.course-grid .course-card').first().waitFor();
    await page.locator('.course-grid .course-card').first().locator('button').click();
    await page.waitForURL('**/student/overview');
  }
}

(async () => {
  const browser = await launchBrowser(chromium);
  const report = [];
  try {
    const student = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const studentErrors = trackErrors(student);
    await login(student, 'student');
    await student.locator('a[href="/student/practice"]').click();
    await student.waitForURL('**/student/practice');
    await student.locator('.a3-set-sidebar > div > button').first().waitFor();
    const questionButtons = student.locator('.a3-question-nav button');
    await questionButtons.first().waitFor();
    const dynamicTotal = await questionButtons.count();
    if (dynamicTotal < 6) throw new Error(`教师精选题组应覆盖六类题型，当前仅 ${dynamicTotal} 题`);
    // Resume can land on a fill/short item. Pick an unsubmitted item with options
    // so the smoke test exercises the option-answer submission path deterministically.
    for (let index = 0; index < dynamicTotal; index += 1) {
      await questionButtons.nth(index).click();
      await student.waitForTimeout(40);
      const hasOptions = await student.locator('.a3-option-list label').count() > 0;
      const submitted = await student.locator('.a3-score-panel').isVisible().catch(() => false);
      if (hasOptions && !submitted) break;
    }
    report.push(await inspect(student, 'a3-student-practice'));

    const alreadySubmitted = await student.locator('.a3-score-panel').isVisible().catch(() => false);
    if (!alreadySubmitted) {
      for (let level = 1; level <= 3; level += 1) {
        const reveal = student.getByRole('button', { name: `查看第 ${level} 级提示`, exact: true });
        await reveal.waitFor();
        await Promise.all([
          student.waitForResponse((response) => response.request().method() === 'POST'
            && response.url().includes(`/hints/${level}:reveal`) && response.status() === 200),
          reveal.click(),
        ]);
        if (await student.locator('.a3-hint-panel > div').count() !== level) {
          throw new Error(`第 ${level} 级提示没有按顺序持久化到界面`);
        }
      }
      await student.locator('.a3-option-list label').first().click();
      await Promise.all([
        student.waitForResponse((response) => response.request().method() === 'POST'
          && response.url().includes('/attempts') && response.status() === 200),
        student.getByRole('button', { name: '提交答案', exact: true }).click(),
      ]);
      await student.locator('.a3-score-panel').waitFor();
    }
    report.push(await inspect(student, 'a3-student-score'));
    await student.reload();
    await student.locator('.a3-score-panel').waitFor();
    if (!await student.getByText(/本题作答已保存/).isVisible()) throw new Error('刷新后未恢复已提交作答状态');
    report.push(await inspect(student, 'a3-student-resume'));
    if (studentErrors.length) throw new Error(`学生端控制台/服务错误：${studentErrors.join(' | ')}`);

    const teacher = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const teacherErrors = trackErrors(teacher);
    await login(teacher, 'teacher');
    await teacher.locator('a[href="/teacher/questions"]').click();
    await teacher.waitForURL('**/teacher/questions');
    const publishedSet = teacher.locator('.a3-teacher-set-list > div > button').filter({ has: teacher.locator('.a3-set-status.published') }).first();
    await publishedSet.waitFor();
    await publishedSet.click();
    await teacher.locator('.a3-question-editor textarea').first().waitFor();
    if (!await teacher.locator('.a3-question-editor textarea').first().isDisabled()) throw new Error('已发布题组仍允许编辑题干');
    if (!await teacher.getByRole('button', { name: '已发布', exact: true }).isDisabled()) throw new Error('已发布题组的发布按钮未锁定');
    report.push(await inspect(teacher, 'a3-teacher-published-readonly'));

    await teacher.getByRole('tab', { name: '生成新题组' }).click();
    await teacher.locator('.a3-model-state').waitFor();
    const unavailable = await teacher.locator('.a3-model-state.unavailable').isVisible().catch(() => false);
    if (unavailable && !await teacher.locator('.a3-generate-action').isDisabled()) throw new Error('模型不可用时生成按钮仍可触发');
    report.push(await inspect(teacher, unavailable ? 'a3-teacher-model-unavailable' : 'a3-teacher-model-available'));
    if (teacherErrors.length) throw new Error(`教师端控制台/服务错误：${teacherErrors.join(' | ')}`);

    process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
  } finally {
    await browser.close();
  }
})().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
