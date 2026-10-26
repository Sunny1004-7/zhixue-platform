import {
  AlertTriangle,
  BookOpenCheck,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  ClipboardCheck,
  Database,
  FileQuestion,
  GitBranch,
  History,
  Layers3,
  Lightbulb,
  LoaderCircle,
  Lock,
  Minus,
  PencilLine,
  Plus,
  RefreshCw,
  Save,
  Send,
  Sparkles,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { ApiError, api } from '../api';
import { useCourse } from '../CourseContext';
import { ErrorState, LoadingState, Surface } from '../components/Primitives';
import type {
  CompilePracticeBlueprintPayload,
  GraphListItem,
  KnowledgeGraph,
  ModelProfile,
  PracticeQuestion,
  QuestionOption,
  QuestionSetDetail,
  QuestionSetSummary,
  QuestionType,
  QuestionTypeCounts,
  UpdateQuestionPayload,
} from '../types';

type SourceMethod = CompilePracticeBlueprintPayload['source_method'];
type DifficultyMode = CompilePracticeBlueprintPayload['difficulty_mode'];
type EditorState = {
  prompt: string;
  options: QuestionOption[];
  correctOptionIds: string[];
  referenceAnswer: string;
  explanation: string;
  cognitiveLevel: string;
  difficulty: number;
};

const questionTypes: Array<{ id: QuestionType; label: string }> = [
  { id: 'single', label: '单选' },
  { id: 'multiple', label: '多选' },
  { id: 'judgment', label: '判断' },
  { id: 'fill', label: '填空' },
  { id: 'short', label: '简答' },
  { id: 'scenario', label: '情境' },
];

const typeLabels = Object.fromEntries(questionTypes.map((item) => [item.id, `${item.label}题`])) as Record<QuestionType, string>;
const emptyCounts = (): QuestionTypeCounts => ({ single: 0, multiple: 0, judgment: 0, fill: 0, short: 0, scenario: 0 });

function teacherPracticeError(reason: unknown, fallback: string) {
  if (!(reason instanceof ApiError)) return fallback;
  if (reason.status === 409) return `修订版本冲突：${reason.message}。请重新载入题组后再操作。`;
  if (reason.status === 422) return `蓝图或题组未通过规则校验：${reason.message}`;
  if (reason.status === 503 || reason.code === 'MODEL_PROFILE_NOT_FEASIBLE') return `模型生成服务不可用：${reason.message}`;
  return reason.message;
}

function referenceAnswer(question: PracticeQuestion) {
  const spec = question.answer_spec ?? {};
  const accepted = spec.accepted_texts;
  if (Array.isArray(accepted) && typeof accepted[0] === 'string') return accepted[0];
  if (typeof spec.reference_answer === 'string') return spec.reference_answer;
  if (typeof spec.text === 'string') return spec.text;
  return '';
}

function correctOptionIds(question: PracticeQuestion) {
  const selected = question.answer_spec?.selected_option_ids;
  if (Array.isArray(selected)) return selected.filter((item): item is string => typeof item === 'string');
  return question.options.filter((item) => item.is_correct).map((item) => item.id);
}

function editorState(question: PracticeQuestion): EditorState {
  return {
    prompt: question.prompt,
    options: question.options.map((item) => ({ ...item })),
    correctOptionIds: correctOptionIds(question),
    referenceAnswer: referenceAnswer(question),
    explanation: question.explanation ?? '',
    cognitiveLevel: question.cognitive_level ?? 'understand',
    difficulty: question.difficulty_prior ?? 0.5,
  };
}

function summaryFromDetail(detail: QuestionSetDetail): QuestionSetSummary {
  const { questions: _questions, course_id: _courseId, quality_status: _quality, source_summary: _source, ...summary } = detail;
  return summary;
}

function TeacherBlueprintDesigner({
  courseId,
  graphs,
  profiles,
  onGenerated,
}: {
  courseId: string;
  graphs: GraphListItem[];
  profiles: ModelProfile[];
  onGenerated: (detail: QuestionSetDetail) => void;
}) {
  const [sourceMethod, setSourceMethod] = useState<SourceMethod>('graph');
  const [difficulty, setDifficulty] = useState<DifficultyMode>('balanced');
  const [graphId, setGraphId] = useState(graphs.find((item) => item.status === 'published')?.id ?? graphs[0]?.id ?? '');
  const [alignmentRunId, setAlignmentRunId] = useState('');
  const [graph, setGraph] = useState<KnowledgeGraph | null>(null);
  const [counts, setCounts] = useState<Record<string, QuestionTypeCounts>>({});
  const [profileId, setProfileId] = useState(profiles.find((item) => item.available)?.id ?? profiles[0]?.id ?? '');
  const [title, setTitle] = useState('课程重点巩固题组');
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    if (!graphs.some((item) => item.id === graphId)) {
      setGraphId(graphs.find((item) => item.status === 'published')?.id ?? graphs[0]?.id ?? '');
    }
  }, [graphId, graphs]);

  useEffect(() => {
    if (!graphId) { setGraph(null); return; }
    let cancelled = false;
    api.teacherGraph(graphId).then((detail) => {
      if (cancelled) return;
      setGraph(detail);
      setCounts((current) => {
        const next = { ...current };
        detail.nodes.forEach((node, index) => {
          if (!next[node.concept_id]) next[node.concept_id] = index < 3
            ? { single: 1, multiple: 0, judgment: 1, fill: 0, short: 0, scenario: 0 }
            : emptyCounts();
        });
        return next;
      });
    }).catch((reason) => { if (!cancelled) setError(teacherPracticeError(reason, '无法读取图谱知识点')); });
    return () => { cancelled = true; };
  }, [graphId]);

  useEffect(() => {
    if (!profiles.some((item) => item.id === profileId)) setProfileId(profiles.find((item) => item.available)?.id ?? profiles[0]?.id ?? '');
  }, [profileId, profiles]);

  const concepts = graph?.nodes ?? [];
  const selectedProfile = profiles.find((item) => item.id === profileId);
  const total = useMemo(() => concepts.reduce((sum, node) => sum + Object.values(counts[node.concept_id] ?? emptyCounts()).reduce((cellSum, value) => cellSum + value, 0), 0), [concepts, counts]);
  const selectedConceptCount = concepts.filter((node) => Object.values(counts[node.concept_id] ?? emptyCounts()).some((value) => value > 0)).length;

  const changeCount = (conceptId: string, type: QuestionType, delta: number) => {
    setCounts((current) => {
      const existing = current[conceptId] ?? emptyCounts();
      return { ...current, [conceptId]: { ...existing, [type]: Math.max(0, Math.min(5, existing[type] + delta)) } };
    });
  };

  const generate = async () => {
    if (!selectedProfile?.available || total === 0) return;
    if (sourceMethod === 'graph' && !graphId) { setError('请选择可读取的课程知识图谱'); return; }
    if (sourceMethod === 'alignment' && !alignmentRunId.trim()) { setError('请选择已完成的材料对齐运行'); return; }
    setBusy(true); setError(''); setStage('正在编译逐知识点题型蓝图');
    try {
      const blueprint = await api.compilePracticeBlueprint(courseId, {
        source_method: sourceMethod,
        difficulty_mode: difficulty,
        graph_id: sourceMethod === 'graph' ? graphId : undefined,
        alignment_run_id: sourceMethod === 'alignment' ? alignmentRunId.trim() : undefined,
        requested_profile_id: selectedProfile.id,
        concepts: concepts.flatMap((node) => {
          const cellCounts = counts[node.concept_id] ?? emptyCounts();
          return Object.values(cellCounts).some((value) => value > 0) ? [{ concept_id: node.concept_id, counts: cellCounts }] : [];
        }),
      });
      setStage(`蓝图 ${blueprint.version} 已编译，共 ${blueprint.total} 题，正在生成并执行质量门禁`);
      const generated = await api.generateQuestionSet(courseId, {
        blueprint_id: blueprint.id,
        title: title.trim(),
        requested_profile_id: selectedProfile.id,
        idempotency_key: `teacher-question-set-${crypto.randomUUID()}`,
      });
      onGenerated(generated);
    } catch (reason) {
      setError(teacherPracticeError(reason, '习题生成失败'));
    } finally {
      setBusy(false); setStage('');
    }
  };

  const methods: Array<{ id: SourceMethod; label: string; detail: string; Icon: typeof History }> = [
    { id: 'history', label: '学习轨迹', detail: '班级已有作答证据', Icon: History },
    { id: 'recorded', label: '课程记录', detail: '已记录知识点索引', Icon: Database },
    { id: 'graph', label: '知识图谱', detail: '按稳定概念标识选题', Icon: GitBranch },
    { id: 'alignment', label: '材料对齐', detail: '复用已审核对齐结果', Icon: Layers3 },
  ];

  return <div className="a3-blueprint-designer">
    {error && <div className="a3-action-error"><AlertTriangle size={16} /><span>{error}</span><button onClick={() => setError('')}>关闭</button></div>}
    <div className="a3-source-methods" aria-label="蓝图来源">{methods.map(({ id, label, detail, Icon }) => <button key={id} className={sourceMethod === id ? 'active' : ''} onClick={() => setSourceMethod(id)}><span><Icon size={17} /></span><div><b>{label}</b><small>{detail}</small></div>{sourceMethod === id && <Check size={15} />}</button>)}</div>
    <div className="a3-blueprint-grid">
      <section className="a3-blueprint-concepts">
        <header><div><span>1. 确定来源与知识点</span><h3>{sourceMethod === 'graph' ? '课程知识图谱' : sourceMethod === 'history' ? '学习轨迹证据' : sourceMethod === 'recorded' ? '课程记录知识点' : '材料对齐结果'}</h3></div><em>{selectedConceptCount} / {concepts.length} 个知识点</em></header>
        <div className="a3-source-fields">
          <label><span>知识点词表</span><select value={graphId} onChange={(event) => setGraphId(event.target.value)}>{graphs.map((item) => <option key={item.id} value={item.id}>{item.title} · {item.status === 'published' ? '已发布' : '草稿'}</option>)}</select></label>
          {sourceMethod === 'alignment' && <label><span>材料对齐运行 ID</span><input value={alignmentRunId} onChange={(event) => setAlignmentRunId(event.target.value)} placeholder="alignment run id" /></label>}
        </div>
        {!graph ? <LoadingState label="正在读取知识点…" /> : <div className="a3-count-table">
          <div className="a3-count-head"><span>知识点</span>{questionTypes.map((item) => <span key={item.id}>{item.label}</span>)}<span>小计</span></div>
          <div className="a3-count-rows">{concepts.map((node) => {
            const nodeCounts = counts[node.concept_id] ?? emptyCounts();
            const subtotal = Object.values(nodeCounts).reduce((sum, value) => sum + value, 0);
            return <div key={node.concept_id} className={subtotal > 0 ? 'selected' : ''}><span title={node.label}><i className={`node-dot ${node.node_type}`} /><b>{node.label}</b></span>{questionTypes.map((type) => <span className="a3-count-stepper" key={type.id}><button aria-label={`减少${node.label}${type.label}题`} disabled={nodeCounts[type.id] === 0} onClick={() => changeCount(node.concept_id, type.id, -1)}><Minus size={12} /></button><b>{nodeCounts[type.id]}</b><button aria-label={`增加${node.label}${type.label}题`} disabled={nodeCounts[type.id] === 5} onClick={() => changeCount(node.concept_id, type.id, 1)}><Plus size={12} /></button></span>)}<strong>{subtotal}</strong></div>;
          })}</div>
        </div>}
      </section>

      <aside className="a3-blueprint-settings">
        <header><span>2. 生成设置</span><h3>蓝图与模型</h3></header>
        <label className="a3-field"><span>题组名称</span><input value={title} maxLength={120} onChange={(event) => setTitle(event.target.value)} /></label>
        <div className="a3-field"><span>难度策略</span><div className="a3-segmented">{(['basic', 'standard', 'balanced', 'challenge'] as DifficultyMode[]).map((item) => <button key={item} className={difficulty === item ? 'active' : ''} onClick={() => setDifficulty(item)}>{{ personalized: '个性化', basic: '基础', standard: '标准', balanced: '均衡', challenge: '挑战' }[item]}</button>)}</div></div>
        <label className="a3-field"><span>生成模型</span><select value={profileId} onChange={(event) => setProfileId(event.target.value)}>{profiles.map((profile) => <option key={profile.id} value={profile.id} disabled={!profile.available}>{profile.display_name}{profile.available ? '' : ' · 不可用'}</option>)}</select></label>
        <div className={`a3-model-state ${selectedProfile?.available ? 'available' : 'unavailable'}`}>{selectedProfile?.available ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}<span>{selectedProfile?.available ? '任务能力、凭据与配置均可用' : selectedProfile?.unavailable_reason || '当前没有可用生成模型'}</span></div>
        <div className="a3-blueprint-total"><FileQuestion size={19} /><div><span>当前生成计划</span><b>{selectedConceptCount} 个知识点 · {total} 道题</b></div></div>
        <button className="a3-generate-action" disabled={busy || !selectedProfile?.available || total === 0 || !title.trim()} onClick={() => void generate()}>{busy ? <LoaderCircle className="spin" size={17} /> : <Sparkles size={17} />}{busy ? stage : `编译并生成 ${total} 道题`}</button>
      </aside>
    </div>
  </div>;
}

function QuestionEditor({
  question,
  revisionVersion,
  readOnly,
  busy,
  onSave,
}: {
  question: PracticeQuestion;
  revisionVersion: number;
  readOnly: boolean;
  busy: boolean;
  onSave: (questionId: string, payload: UpdateQuestionPayload) => void;
}) {
  const [editor, setEditor] = useState(() => editorState(question));
  useEffect(() => { setEditor(editorState(question)); }, [question]);

  const toggleCorrect = (optionId: string) => {
    if (readOnly) return;
    setEditor((current) => ({
      ...current,
      correctOptionIds: question.type === 'multiple'
        ? current.correctOptionIds.includes(optionId) ? current.correctOptionIds.filter((item) => item !== optionId) : [...current.correctOptionIds, optionId]
        : [optionId],
    }));
  };

  const save = () => {
    const objective = question.type === 'single' || question.type === 'multiple' || question.type === 'judgment';
    const currentSpec = question.answer_spec ?? {};
    const answerSpec = objective
      ? { ...currentSpec, selected_option_ids: editor.correctOptionIds }
      : question.type === 'fill'
        ? { ...currentSpec, accepted_texts: [editor.referenceAnswer.trim()] }
        : { ...currentSpec, reference_answer: editor.referenceAnswer.trim() };
    onSave(question.id, {
      expected_revision_version: revisionVersion,
      prompt: editor.prompt.trim(),
      options: editor.options.map((option) => ({ id: option.id, content: option.content.trim(), is_correct: editor.correctOptionIds.includes(option.id) })),
      answer_spec: answerSpec,
      rubric: question.rubric ?? [],
      explanation: editor.explanation.trim(),
      cognitive_level: editor.cognitiveLevel,
      difficulty_prior: editor.difficulty,
    });
  };

  const objective = question.type === 'single' || question.type === 'multiple' || question.type === 'judgment';
  return <div className="a3-question-editor">
    <header><div><span>{typeLabels[question.type]} · 第 {question.position} 题</span><h3>{readOnly ? '已发布题目' : '编辑题目'}</h3></div>{readOnly && <em><Lock size={14} />发布修订只读</em>}</header>
    <label className="a3-editor-field"><span>题干</span><textarea value={editor.prompt} disabled={readOnly} onChange={(event) => setEditor((current) => ({ ...current, prompt: event.target.value }))} /></label>
    {objective && <div className="a3-editor-options"><span>选项与正确答案</span>{editor.options.map((option, index) => <div key={option.id}>
      <button className={editor.correctOptionIds.includes(option.id) ? 'correct' : ''} disabled={readOnly} aria-label={`设为${question.type === 'multiple' ? '正确选项' : '正确答案'} ${String.fromCharCode(65 + index)}`} onClick={() => toggleCorrect(option.id)}>{editor.correctOptionIds.includes(option.id) ? <Check size={14} /> : <CircleDot size={14} />}</button>
      <b>{String.fromCharCode(65 + index)}</b><input value={option.content} disabled={readOnly} onChange={(event) => setEditor((current) => ({ ...current, options: current.options.map((item) => item.id === option.id ? { ...item, content: event.target.value } : item) }))} />
    </div>)}</div>}
    {!objective && <label className="a3-editor-field"><span>{question.type === 'fill' ? '可接受答案' : '参考答案'}</span><textarea value={editor.referenceAnswer} disabled={readOnly} onChange={(event) => setEditor((current) => ({ ...current, referenceAnswer: event.target.value }))} /></label>}
    <label className="a3-editor-field"><span>解析</span><textarea value={editor.explanation} disabled={readOnly} onChange={(event) => setEditor((current) => ({ ...current, explanation: event.target.value }))} /></label>
    <div className="a3-editor-row"><label><span>认知层级</span><select value={editor.cognitiveLevel} disabled={readOnly} onChange={(event) => setEditor((current) => ({ ...current, cognitiveLevel: event.target.value }))}><option value="remember">记忆</option><option value="understand">理解</option><option value="apply">应用</option><option value="analyze">分析</option><option value="evaluate">评价</option></select></label><label><span>先验难度 {Math.round(editor.difficulty * 100)}%</span><input type="range" min="0.1" max="0.9" step="0.1" value={editor.difficulty} disabled={readOnly} onChange={(event) => setEditor((current) => ({ ...current, difficulty: Number(event.target.value) }))} /></label></div>
    <section className="a3-editor-hints"><header><Lightbulb size={16} /><span><b>渐进提示</b><small>{question.hints_available} 级，发布前由质量规则检查答案泄漏风险</small></span></header></section>
    {!readOnly && <footer><span>保存时校验当前题组修订版本 {revisionVersion}</span><button disabled={busy || !editor.prompt.trim() || (objective && editor.correctOptionIds.length === 0)} onClick={save}>{busy ? <LoaderCircle className="spin" size={15} /> : <Save size={15} />}保存题目</button></footer>}
  </div>;
}

export default function TeacherQuestionsPage() {
  const { courseId } = useCourse();
  const [mode, setMode] = useState<'manage' | 'generate'>('manage');
  const [sets, setSets] = useState<QuestionSetSummary[] | null>(null);
  const [graphs, setGraphs] = useState<GraphListItem[] | null>(null);
  const [profiles, setProfiles] = useState<ModelProfile[] | null>(null);
  const [activeSet, setActiveSet] = useState<QuestionSetDetail | null>(null);
  const [activeQuestionId, setActiveQuestionId] = useState('');
  const [loadingSet, setLoadingSet] = useState(false);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');

  const openSet = useCallback(async (setId: string) => {
    setLoadingSet(true); setError('');
    try {
      const detail = await api.questionSet(setId);
      setActiveSet(detail);
      setActiveQuestionId((current) => detail.questions.some((item) => item.id === current) ? current : detail.questions[0]?.id ?? '');
    } catch (reason) {
      setError(teacherPracticeError(reason, '无法打开题组'));
    } finally {
      setLoadingSet(false);
    }
  }, []);

  const load = useCallback(async () => {
    setSets(null); setGraphs(null); setProfiles(null); setActiveSet(null); setError('');
    try {
      const [questionSets, graphItems, modelProfiles] = await Promise.all([
        api.teacherQuestionSets(courseId),
        api.teacherGraphs(courseId),
        api.modelProfiles('a3.question_generation'),
      ]);
      setSets(questionSets.items); setGraphs(graphItems); setProfiles(modelProfiles);
      if (questionSets.items[0]) await openSet(questionSets.items[0].id);
    } catch (reason) {
      setError(teacherPracticeError(reason, '无法读取题组管理数据'));
    }
  }, [courseId, openSet]);

  useEffect(() => { void load(); }, [load]);

  const replaceSet = (detail: QuestionSetDetail) => {
    setActiveSet(detail);
    setSets((current) => current?.map((item) => item.id === detail.id ? summaryFromDetail(detail) : item) ?? null);
    setActiveQuestionId((current) => detail.questions.some((item) => item.id === current) ? current : detail.questions[0]?.id ?? '');
  };

  const saveQuestion = async (questionId: string, payload: UpdateQuestionPayload) => {
    setBusy(`save-${questionId}`); setError('');
    try { replaceSet(await api.updateTeacherQuestion(questionId, payload)); }
    catch (reason) { setError(teacherPracticeError(reason, '题目保存失败')); }
    finally { setBusy(''); }
  };

  const validate = async () => {
    if (!activeSet) return;
    setBusy('validate'); setError('');
    try { replaceSet(await api.validateQuestionSet(activeSet.id, activeSet.revision_version)); }
    catch (reason) { setError(teacherPracticeError(reason, '题组质量校验失败')); }
    finally { setBusy(''); }
  };

  const publish = async () => {
    if (!activeSet) return;
    setBusy('publish'); setError('');
    try { replaceSet(await api.publishQuestionSet(activeSet.id, activeSet.revision_version)); }
    catch (reason) { setError(teacherPracticeError(reason, '题组发布失败')); }
    finally { setBusy(''); }
  };

  const acceptGenerated = (detail: QuestionSetDetail) => {
    setSets((current) => [summaryFromDetail(detail), ...(current?.filter((item) => item.id !== detail.id) ?? [])]);
    setActiveSet(detail); setActiveQuestionId(detail.questions[0]?.id ?? ''); setMode('manage');
  };

  if (error && (!sets || !graphs || !profiles)) return <ErrorState message={error} retry={() => void load()} />;
  if (!sets || !graphs || !profiles) return <LoadingState label="正在读取题组、知识图谱与模型状态…" />;

  const activeQuestion = activeSet?.questions.find((item) => item.id === activeQuestionId) ?? activeSet?.questions[0] ?? null;
  const publishedCount = sets.filter((item) => item.status === 'published').length;
  const draftCount = sets.length - publishedCount;
  const readOnly = activeSet?.status === 'published';
  const canPublish = activeSet && !readOnly && (activeSet.quality_status === 'passed' || activeSet.quality_status === 'teacher_validated' || activeSet.status === 'validated');

  return <div className="a3-teacher-page">
    <section className="a3-teacher-hero"><div><span><ClipboardCheck size={16} />TraceQ · 可审核题组流水线</span><h2>智能习题生成</h2><p>按课程知识点编译六题型蓝图，生成后由教师逐题复核、质量校验并发布。</p></div><div className="a3-teacher-stats"><span><b>{sets.length}</b>题组</span><span><b>{draftCount}</b>待审核</span><span><b>{publishedCount}</b>已发布</span><button aria-label="刷新题组" title="刷新题组" onClick={() => void load()}><RefreshCw size={17} /></button></div></section>
    <div className="a3-page-tabs" role="tablist"><button role="tab" aria-selected={mode === 'manage'} className={mode === 'manage' ? 'active' : ''} onClick={() => setMode('manage')}><BookOpenCheck size={16} />题组管理</button><button role="tab" aria-selected={mode === 'generate'} className={mode === 'generate' ? 'active' : ''} onClick={() => setMode('generate')}><Sparkles size={16} />生成新题组</button></div>
    {error && <div className="a3-action-error"><AlertTriangle size={16} /><span>{error}</span><button onClick={() => setError('')}>关闭</button></div>}

    {mode === 'generate' ? <Surface className="a3-generation-surface"><TeacherBlueprintDesigner courseId={courseId} graphs={graphs} profiles={profiles} onGenerated={acceptGenerated} /></Surface> : <div className="a3-teacher-manage-layout">
      <aside className="a3-teacher-set-list"><header><span>课程题组</span><em>{sets.length}</em></header><div>{sets.map((item) => <button key={item.id} className={activeSet?.id === item.id ? 'active' : ''} onClick={() => void openSet(item.id)}><span className={`a3-set-status ${item.status}`}>{item.status === 'published' ? '已发布' : item.status === 'validated' ? '已校验' : '草稿'}</span><b>{item.title}</b><small>{item.total} 题 · 修订 {item.revision_no} · {item.source_kind === 'curated_seed' ? '教师精选' : '模型生成'}</small><ChevronRight size={15} /></button>)}</div><button className="a3-new-set" onClick={() => setMode('generate')}><Plus size={16} />生成新题组</button></aside>
      <Surface className="a3-teacher-set-workspace">{loadingSet || !activeSet ? <LoadingState label="正在读取题组修订…" /> : <>
        <header className="a3-set-detail-header"><div><span>{activeSet.status === 'published' ? <Lock size={14} /> : <PencilLine size={14} />}{activeSet.status === 'published' ? '已发布修订，只读' : '工作修订，可编辑'}</span><h3>{activeSet.title}</h3><p>{activeSet.total} 题 · 修订 {activeSet.revision_no} · 质量状态 {activeSet.quality_status}</p></div><div>{!readOnly && <button disabled={Boolean(busy)} onClick={() => void validate()}>{busy === 'validate' ? <LoaderCircle className="spin" size={15} /> : <ClipboardCheck size={15} />}质量校验</button>}<button className="primary" disabled={!canPublish || Boolean(busy)} onClick={() => void publish()}>{busy === 'publish' ? <LoaderCircle className="spin" size={15} /> : readOnly ? <CheckCircle2 size={15} /> : <Send size={15} />}{readOnly ? '已发布' : '发布题组'}</button></div></header>
        <div className="a3-set-editor-layout"><nav className="a3-teacher-question-list" aria-label="题目列表">{activeSet.questions.map((item, index) => <button key={item.id} className={activeQuestion?.id === item.id ? 'active' : ''} onClick={() => setActiveQuestionId(item.id)}><span>{index + 1}</span><div><b>{typeLabels[item.type]}</b><small>{item.prompt}</small></div><em>{item.concepts[0]?.label ?? '综合'}</em></button>)}</nav>{activeQuestion ? <QuestionEditor question={activeQuestion} revisionVersion={activeSet.revision_version} readOnly={Boolean(readOnly)} busy={busy === `save-${activeQuestion.id}`} onSave={(questionId, payload) => void saveQuestion(questionId, payload)} /> : <div className="a3-empty-state"><FileQuestion size={26} /><p>题组中暂无题目</p></div>}</div>
      </>}</Surface>
    </div>}
  </div>;
}
