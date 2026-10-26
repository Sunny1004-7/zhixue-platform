const path = require('path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const { launchBrowser } = require('./browser.cjs');

const baseUrl = process.env.A4_A6_BASE_URL || 'http://127.0.0.1:4174';
const outputDir = path.resolve(process.env.ZHIXING_QA_OUTPUT_DIR || path.join(__dirname, '..', '.qa-artifacts'));
require('fs').mkdirSync(outputDir, { recursive: true });
const viewports = [
  { name: 'desktop', width: 1440, height: 900 },
  { name: 'mobile', width: 390, height: 844 },
];

function trackErrors(page) {
  const errors = [];
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(`console: ${message.text()}`);
  });
  page.on('requestfailed', (request) => {
    errors.push(`request: ${request.url()} ${request.failure()?.errorText || ''}`);
  });
  page.on('response', (response) => {
    if (response.status() >= 500) errors.push(`response: ${response.status()} ${response.url()}`);
  });
  return errors;
}

async function inspect(page, label) {
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(250);
  const state = await page.evaluate(() => ({
    path: location.pathname,
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
    emptyButtons: [...document.querySelectorAll('button')]
      .filter((item) => !item.textContent?.trim()
        && !item.getAttribute('aria-label')
        && !item.getAttribute('title'))
      .length,
    bodyText: document.body.innerText.slice(0, 2000),
  }));
  if (state.scrollWidth > state.clientWidth + 1) {
    throw new Error(`${label} horizontal overflow ${state.scrollWidth}/${state.clientWidth}`);
  }
  if (state.emptyButtons) throw new Error(`${label} has ${state.emptyButtons} unnamed buttons`);
  await page.screenshot({ path: path.join(outputDir, `${label}.png`), fullPage: false });
  return state;
}

async function login(page, role) {
  await page.goto(`${baseUrl}/login`);
  // Stable semantic hooks keep this smoke test independent of localized copy.
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

async function visit(browser, role, route, label) {
  const report = [];
  for (const viewport of viewports) {
    const page = await browser.newPage({ viewport });
    const errors = trackErrors(page);
    try {
      await login(page, role);
      await page.goto(`${baseUrl}${route}`);
      await page.waitForURL(`**${route}`);
      const state = await inspect(page, `${label}-${viewport.name}`);
      if (!state.bodyText.trim()) throw new Error(`${label} rendered an empty document`);
      if (errors.length) throw new Error(`${label} runtime errors: ${errors.join(' | ')}`);
      report.push({ role, route, viewport: viewport.name, ...state });
    } finally {
      await page.close();
    }
  }
  return report;
}

(async () => {
  const browser = await launchBrowser(chromium);
  try {
    const report = [];
    report.push(...await visit(browser, 'student', '/student/resources', 'a4-student-resources'));
    report.push(...await visit(browser, 'student', '/student/tutor', 'a5-student-tutor'));
    report.push(...await visit(browser, 'teacher', '/teacher/students', 'a6-teacher-students'));
    report.push(...await visit(browser, 'teacher', '/teacher/videos', 'a4-teacher-videos'));
    process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
  } finally {
    await browser.close();
  }
})().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
