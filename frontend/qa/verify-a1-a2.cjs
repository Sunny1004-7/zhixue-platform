const path = require('path');
const { chromium, request } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const { launchBrowser } = require('./browser.cjs');

const baseUrl = process.env.A1_A2_BASE_URL || 'http://127.0.0.1:5191';
const apiBase = process.env.A1_A2_API_BASE || 'http://127.0.0.1:8111/api/v1';
const outputDir = path.resolve(process.env.ZHIXING_QA_OUTPUT_DIR || path.join(__dirname, '..', '.qa-artifacts'));
require('fs').mkdirSync(outputDir, { recursive: true });
const graphTitle = 'A1 A2 浏览器联合验收图谱';

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

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
  assert(state.scrollWidth <= state.clientWidth, `${name} 出现横向溢出：${state.scrollWidth}/${state.clientWidth}`);
  assert(state.emptyButtons === 0, `${name} 存在 ${state.emptyButtons} 个无名称按钮`);
  await page.screenshot({ path: path.join(outputDir, `${name}.png`), fullPage: false });
  return state;
}

function trackErrors(page) {
  const errors = [];
  let allowBlockedPublish = false;
  page.on('console', (message) => {
    if (message.type() !== 'error') return;
    if (allowBlockedPublish && message.text().includes('422')) return;
    errors.push(message.text());
  });
  page.on('requestfailed', (failed) => errors.push(`${failed.url()}: ${failed.failure()?.errorText}`));
  page.on('response', (response) => {
    if (response.status() < 400) return;
    if (allowBlockedPublish && response.status() === 422 && response.url().includes(':publish')) return;
    errors.push(`${response.status()} ${response.url()}`);
  });
  return {
    errors,
    allowExpectedPublishBlock(value) { allowBlockedPublish = value; },
  };
}

async function login(page, role) {
  await page.goto(`${baseUrl}/login`);
  if (role === 'teacher') await page.locator('.zx-role').filter({ hasText: '教师' }).click();
  await page.locator('input[autocomplete="username"]').fill(`${role}@zhixing.edu.cn`);
  await page.locator('input[autocomplete="current-password"]').fill('zhixing2026');
  await page.locator('.zx-submit').click();
  await page.waitForURL(role === 'teacher' ? '**/teacher/overview' : '**/student/courses');
  return page.evaluate(() => window.sessionStorage.getItem('zhixing-access-token'));
}

async function apiContext(token) {
  assert(token, '登录后没有取得真实访问令牌');
  return request.newContext({
    baseURL: `${apiBase.replace(/\/$/, '')}/`,
    extraHTTPHeaders: { Authorization: `Bearer ${token}` },
  });
}

async function postEvent(api, body) {
  const response = await api.post('student/courses/machine-learning/events', { data: body });
  assert(response.status() === 200, `A1 事件写入失败：${response.status()} ${await response.text()}`);
  return response.json();
}

function eventPayload(key, graphId, node, dwellSeconds, occurredAt) {
  return {
    idempotency_key: key,
    event_type: 'knowledge_card_opened',
    object_type: 'knowledge_graph_node',
    object_id: node.id,
    concepts: [{ concept_id: node.concept_id, weight: 1 }],
    occurred_at: occurredAt.toISOString(),
    payload: { graph_id: graphId, dwell_seconds: dwellSeconds, foreground_ratio: 1 },
  };
}

(async () => {
  const browser = await launchBrowser(chromium);
  const report = [];
  let teacherApi;
  let studentApi;
  try {
    const teacher = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const teacherLog = trackErrors(teacher);
    const teacherToken = await login(teacher, 'teacher');
    teacherApi = await apiContext(teacherToken);
    await teacher.locator('a[href="/teacher/graphs"]').click();
    await teacher.waitForURL('**/teacher/graphs');

    await teacher.getByPlaceholder('输入新图谱名称').fill(graphTitle);
    const [createdResponse] = await Promise.all([
      teacher.waitForResponse((response) => response.request().method() === 'POST'
        && response.url().includes('/teacher/courses/machine-learning/graphs') && response.status() === 201),
      teacher.getByRole('button', { name: '新建图谱', exact: true }).click(),
    ]);
    const createdGraph = await createdResponse.json();
    await teacher.locator('.teacher-graph-workspace h3').filter({ hasText: graphTitle }).waitFor();

    await teacher.getByRole('button', { name: '导入教学材料', exact: true }).click();
    const sourceDialog = teacher.getByRole('dialog', { name: '导入教学材料' });
    await sourceDialog.waitFor();
    await sourceDialog.getByRole('button', { name: '输入自然语言', exact: true }).click();
    await sourceDialog.locator('textarea').fill('量子引力；量子引力');
    await Promise.all([
      teacher.waitForResponse((response) => response.request().method() === 'POST'
        && response.url().includes('/alignment-runs') && response.status() === 201),
      sourceDialog.getByRole('button', { name: '开始识别与对齐', exact: true }).click(),
    ]);
    const rows = sourceDialog.locator('.alignment-row');
    await rows.first().waitFor();
    assert(await rows.count() === 2, '重复开放概念没有形成两条待复核提及');

    const firstRow = rows.first();
    await firstRow.locator('.alignment-new-concept input').fill('量子引力导论');
    const [decisionResponse] = await Promise.all([
      teacher.waitForResponse((response) => response.request().method() === 'POST'
        && response.url().includes('/alignment-reviews/') && response.status() === 200),
      firstRow.getByRole('button', { name: '新概念', exact: true }).click(),
    ]);
    const decision = await decisionResponse.json();
    const selectedIds = new Set(decision.mentions.map((item) => item.review?.selected_concept_id));
    assert(decision.status === 'completed', '同名开放概念归并后对齐任务仍未完成');
    assert(selectedIds.size === 1 && !selectedIds.has(null), '同名开放概念没有归并到同一规范 Concept');
    assert(new Set(decision.mentions.map((item) => item.review?.decision)).size === 2,
      '开放概念创建项和精确归并项没有分别留下审计决定');

    const [appliedResponse] = await Promise.all([
      teacher.waitForResponse((response) => response.request().method() === 'POST'
        && response.url().includes(':apply') && response.status() === 200),
      sourceDialog.getByRole('button', { name: '仅加入知识点', exact: true }).click(),
    ]);
    const draft = await appliedResponse.json();
    assert(draft.revision_status === 'draft', '开放概念没有写入当前草稿修订');
    assert(draft.nodes.length === 1 && draft.nodes[0].label === '量子引力导论',
      '精确归并后的开放概念草稿节点不唯一');
    report.push(await inspect(teacher, 'a1-a2-teacher-open-concept-draft'));

    teacherLog.allowExpectedPublishBlock(true);
    const [blockedResponse] = await Promise.all([
      teacher.waitForResponse((response) => response.request().method() === 'POST'
        && response.url().includes(':publish') && response.status() === 422),
      teacher.getByRole('button', { name: '发布图谱', exact: true }).click(),
    ]);
    await teacher.waitForTimeout(100);
    teacherLog.allowExpectedPublishBlock(false);
    const blocked = await blockedResponse.json();
    const issueCodes = new Set(blocked.detail.issues.map((item) => item.code));
    assert(issueCodes.has('too_few_nodes') && issueCodes.has('missing_definition'),
      '发布硬门没有同时阻断单节点和缺失定义');
    const publishError = teacher.locator('.inline-error').filter({ hasText: '图谱未通过发布硬门' });
    await publishError.waitFor();
    await publishError.scrollIntoViewIfNeeded();
    report.push(await inspect(teacher, 'a1-a2-teacher-publish-blocked'));

    await teacher.getByRole('button', { name: '编辑图谱', exact: true }).click();
    const editor = teacher.getByRole('dialog', { name: '编辑知识图谱' });
    await editor.waitFor();
    await editor.getByLabel('定义').fill('研究量子理论与引力相容性的课程扩展概念。');
    await editor.getByLabel('教师来源说明（可选）').fill('教师确认该概念用于课程拓展单元。');
    await Promise.all([
      teacher.waitForResponse((response) => response.request().method() === 'PATCH'
        && response.url().includes('/nodes/') && response.status() === 200),
      editor.getByRole('button', { name: '保存知识点', exact: true }).click(),
    ]);

    await editor.getByRole('button', { name: '新增知识点', exact: true }).click();
    await editor.getByLabel('知识点名称').fill('广义相对论拓展');
    await editor.getByLabel('定义').fill('用于连接时空几何与引力描述的拓展知识点。');
    await editor.getByLabel('教师来源说明（可选）').fill('教师确认的课程拓展先备知识。');
    await Promise.all([
      teacher.waitForResponse((response) => response.request().method() === 'POST'
        && response.url().endsWith('/nodes') && response.status() === 200),
      editor.getByRole('button', { name: '保存知识点', exact: true }).click(),
    ]);
    await editor.getByRole('button', { name: '关闭图谱编辑器' }).click();
    await editor.waitFor({ state: 'hidden' });

    const [publishedResponse] = await Promise.all([
      teacher.waitForResponse((response) => response.request().method() === 'POST'
        && response.url().includes(':publish') && response.status() === 200),
      teacher.getByRole('button', { name: '发布图谱', exact: true }).click(),
    ]);
    const published = await publishedResponse.json();
    assert(published.review_status === 'teacher_validated' && published.quality?.hard_pass,
      '补齐定义和最小结构后仍未通过教师发布硬门');
    report.push(await inspect(teacher, 'a1-a2-teacher-published'));

    const teacherRead = await teacherApi.get(`teacher/graphs/${createdGraph.id}`);
    assert(teacherRead.status() === 200, '浏览器操作后的图谱无法通过后端 API 重新读取');
    const persisted = await teacherRead.json();
    assert(persisted.revision_status === 'published' && persisted.nodes.length === 2,
      '浏览器写入没有跨请求持久化到 SQLite');
    assert(teacherLog.errors.length === 0, `教师端控制台/服务错误：${teacherLog.errors.join(' | ')}`);

    const student = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const studentLog = trackErrors(student);
    const studentToken = await login(student, 'student');
    studentApi = await apiContext(studentToken);
    await student.locator('.course-grid .course-card').first().waitFor();
    await student.locator('.course-grid .course-card').first().locator('button').click();
    await student.waitForURL('**/student/overview');

    const masteryResponse = await studentApi.get('student/courses/machine-learning/mastery');
    assert(masteryResponse.status() === 200, '无法读取 A1 真实掌握状态');
    const mastery = await masteryResponse.json();
    const byLabel = new Map(mastery.map((item) => [item.label, item.concept_id]));
    const prerequisiteId = byLabel.get('损失函数');
    const targetId = byLabel.get('梯度下降');
    assert(prerequisiteId && targetId, '清洁种子库缺少 A1/A2 联调知识点');
    const sourceGraphResponse = await studentApi.get('student/courses/machine-learning/graph-resources/ml-g1');
    assert(sourceGraphResponse.status() === 200, '无法读取已发布的学习事件来源图谱');
    const sourceGraph = await sourceGraphResponse.json();
    const targetNode = sourceGraph.nodes.find((item) => item.concept_id === targetId);
    const prerequisiteNode = sourceGraph.nodes.find((item) => item.concept_id === prerequisiteId);
    assert(targetNode && prerequisiteNode, '学习事件引用的知识点没有已发布节点');
    const now = new Date();
    const forged = await studentApi.post('student/courses/machine-learning/events', { data: {
      idempotency_key: 'browser-forged-score', event_type: 'answer_scored',
      object_type: 'question', object_id: 'unverified-question',
      concepts: [{ concept_id: targetId, weight: 1 }], outcome: 1,
      upstream_confidence: 1, alignment_confidence: 1, occurred_at: now.toISOString(),
      payload: { grading_mode: 'objective_rule' },
    } });
    assert(forged.status() === 403, '浏览器提交的评分结果没有被拒绝');
    await postEvent(studentApi, eventPayload(
      'browser-a1-target-1', sourceGraph.id, targetNode, 120, new Date(now.getTime() - 120000),
    ));
    const temporal = await postEvent(studentApi, eventPayload(
      'browser-a1-target-2', sourceGraph.id, targetNode, 120, new Date(now.getTime() - 60000),
    ));
    const temporalTarget = temporal.changes.find((item) => item.concept_id === targetId);
    assert(temporalTarget?.model_version.includes('temporal-evidence-1.0'),
      '两条有效事件后 EvidenceTemporalResidual 未进入生产更新');

    const prerequisitePayload = eventPayload('browser-a1-prerequisite', sourceGraph.id, prerequisiteNode, 15, now);
    const propagated = await postEvent(studentApi, prerequisitePayload);
    const propagatedById = new Map(propagated.changes.map((item) => [item.concept_id, item]));
    assert(propagatedById.has(prerequisiteId) && propagatedById.has(targetId),
      '先修状态变化没有重放已有下游状态');
    assert(propagatedById.get(targetId).model_version.includes('+a2-graph'),
      '下游重放没有应用已发布 A2 图约束');
    const duplicate = await postEvent(studentApi, prerequisitePayload);
    assert(duplicate.duplicate === true, 'A1 联调事件重复提交没有保持幂等');

    await student.locator('a[href="/student/resources"]').click();
    await student.waitForURL('**/student/resources');
    const graphCard = student.locator('.graph-card-grid article').filter({ hasText: graphTitle });
    await graphCard.waitFor();
    await graphCard.getByRole('button', { name: /进入图谱/ }).click();
    const graphDialog = student.getByRole('dialog');
    await graphDialog.waitFor();
    const novelGraphNode = graphDialog.locator('.graph-node').filter({ hasText: '量子引力' }).first();
    await novelGraphNode.click();
    const knowledgeCard = graphDialog.locator('.knowledge-card');
    await knowledgeCard.waitFor();
    assert(await knowledgeCard.getByRole('heading', { name: '量子引力导论', exact: true }).count() === 1,
      '学生端知识卡未读取到教师发布的开放概念');
    report.push(await inspect(student, 'a1-a2-student-published-graph'));

    await graphDialog.getByRole('button', { name: '关闭', exact: true }).click();
    await student.locator('a[href="/student/overview"]').click();
    await student.waitForURL('**/student/overview');
    await student.locator('.overview-hero').waitFor();
    report.push(await inspect(student, 'a1-a2-student-trajectory'));
    assert(studentLog.errors.length === 0, `学生端控制台/服务错误：${studentLog.errors.join(' | ')}`);

    process.stdout.write(`${JSON.stringify({
      report,
      evidence: {
        graph_id: createdGraph.id,
        revision_id: published.revision_id,
        merged_concept_id: [...selectedIds][0],
        publish_gate_codes: [...issueCodes].sort(),
        forged_score_status: forged.status(),
        temporal_model_version: temporalTarget.model_version,
        propagated_concepts: [...propagatedById.keys()],
        duplicate_event: duplicate.duplicate,
      },
    }, null, 2)}\n`);
  } finally {
    if (teacherApi) await teacherApi.dispose();
    if (studentApi) await studentApi.dispose();
    await browser.close();
  }
})().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
