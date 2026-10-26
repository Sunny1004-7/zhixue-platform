import { useAuth } from "../AuthContext";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Brain,
  Check,
  CheckCircle2,
  CircleHelp,
  FileQuestion,
  Lightbulb,
  LoaderCircle,
  RefreshCw,
  Send,
  Sparkles,
  Target,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { ApiError } from "../errors";
import { useApi } from "../RuntimeContext";
import { useCourse } from "../CourseContext";
import { ErrorState, LoadingState, Surface } from "../components/Primitives";
import type {
  KnowledgeState,
  ModelProfile,
  PracticeQuestion,
  PracticeScore,
  QuestionSetDetail,
  QuestionSetProgress,
  QuestionSetSummary,
  QuestionType,
  RevealedHint,
} from "../types";

type AnswerDraft = { selected: string[]; text: string };

const typeLabels: Record<QuestionType, string> = {
  single: "单选题",
  multiple: "多选题",
  judgment: "判断题",
  fill: "填空题",
  short: "简答题",
  scenario: "情境分析",
};

function scorePercent(value: number) {
  return Math.round(value <= 1 ? value * 100 : value);
}

function practiceError(reason: unknown, fallback: string) {
  if (!(reason instanceof ApiError)) return fallback;
  if (reason.status === 409)
    return `题组修订已变化，请重新打开后继续：${reason.message}`;
  if (reason.status === 422)
    return `当前学习证据不足以编译这份练习：${reason.message}`;
  if (reason.status === 503 || reason.code === "MODEL_PROFILE_NOT_FEASIBLE")
    return `所选模型当前不可用：${reason.message}`;
  return reason.message;
}

function answerDraft(question: PracticeQuestion): AnswerDraft {
  const answer = question.attempt_state?.answer;
  const selected =
    answer && Array.isArray(answer.selected_option_ids)
      ? answer.selected_option_ids.filter(
          (item): item is string => typeof item === "string",
        )
      : [];
  const text = answer && typeof answer.text === "string" ? answer.text : "";
  return { selected, text };
}

function feedbackText(score: PracticeScore) {
  const summary =
    score.feedback.summary ?? score.feedback.message ?? score.feedback.feedback;
  return typeof summary === "string" ? summary : "";
}

function setConceptLabels(item: QuestionSetSummary) {
  return (
    item.concepts
      .slice(0, 3)
      .map((concept) => concept.label)
      .join("、") || "综合知识点"
  );
}

function StudentGenerationDialog({
  courseId,
  onClose,
  onGenerated,
}: {
  courseId: string;
  onClose: () => void;
  onGenerated: (questionSet: QuestionSetDetail) => void;
}) {
  const api = useApi();
  const [knowledge, setKnowledge] = useState<KnowledgeState[] | null>(null);
  const [profiles, setProfiles] = useState<ModelProfile[] | null>(null);
  const [selectedConcepts, setSelectedConcepts] = useState<string[]>([]);
  const [profileId, setProfileId] = useState("");
  const [difficulty, setDifficulty] = useState<
    "personalized" | "basic" | "standard" | "challenge"
  >("personalized");
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api.studentOverview(courseId),
      api.modelProfiles("a3.question_generation"),
    ])
      .then(([overview, modelProfiles]) => {
        if (cancelled) return;
        const ordered = [...overview.knowledge_states].sort(
          (left, right) => left.mastery - right.mastery,
        );
        setKnowledge(ordered);
        setSelectedConcepts(
          ordered
            .filter((item) => item.evidence_count > 0)
            .slice(0, 3)
            .map((item) => item.concept_id),
        );
        setProfiles(modelProfiles);
        setProfileId(
          modelProfiles.find((item) => item.available)?.id ??
            modelProfiles[0]?.id ??
            "",
        );
      })
      .catch((reason) => {
        if (!cancelled)
          setError(practiceError(reason, "无法读取学习证据与模型状态"));
      });
    return () => {
      cancelled = true;
    };
  }, [courseId]);

  const selectedProfile = profiles?.find((item) => item.id === profileId);
  const selectedStates =
    knowledge?.filter((item) => selectedConcepts.includes(item.concept_id)) ??
    [];
  const total = selectedStates.length * 4;

  const toggleConcept = (conceptId: string) => {
    setSelectedConcepts((current) =>
      current.includes(conceptId)
        ? current.filter((item) => item !== conceptId)
        : [...current, conceptId],
    );
  };

  const generate = async () => {
    if (!selectedProfile?.available || selectedStates.length === 0) return;
    setBusy(true);
    setError("");
    setStage("正在依据学习证据编译蓝图");
    try {
      const blueprint = await api.compilePracticeBlueprint(courseId, {
        source_method: "history",
        difficulty_mode: difficulty,
        requested_profile_id: selectedProfile.id,
        concepts: selectedStates.map((item) => ({
          concept_id: item.concept_id,
          counts: {
            single: 2,
            multiple: 0,
            judgment: 1,
            fill: 1,
            short: 0,
            scenario: 0,
          },
        })),
      });
      setStage(`蓝图已编译，共 ${blueprint.total} 题，正在请求模型生成并校验`);
      const generated = await api.generateQuestionSet(courseId, {
        blueprint_id: blueprint.id,
        title: `个性化巩固练习 · ${new Date().toLocaleDateString("zh-CN")}`,
        requested_profile_id: selectedProfile.id,
        idempotency_key: `student-question-set-${crypto.randomUUID()}`,
      });
      onGenerated(generated);
    } catch (reason) {
      setError(practiceError(reason, "个性化练习生成失败"));
    } finally {
      setBusy(false);
      setStage("");
    }
  };

  return (
    <div className="dialog-backdrop a3-dialog-backdrop" onMouseDown={onClose}>
      <section
        className="a3-generation-dialog"
        role="dialog"
        aria-modal="true"
        aria-label="生成个性化练习"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header>
          <div>
            <span>
              <Sparkles size={15} />
              知学智教 · 个性化练习
            </span>
            <h3>生成个性化练习</h3>
            <p>
              基于当前课程已有学习证据编译题型蓝图，并交由可用模型生成与校验。
            </p>
          </div>
          <button aria-label="关闭" onClick={onClose}>
            <X size={18} />
          </button>
        </header>
        {error && (
          <div className="a3-action-error">
            <AlertTriangle size={16} />
            <span>{error}</span>
          </div>
        )}
        {!knowledge || !profiles ? (
          <LoadingState label="正在读取学习证据与模型可用性…" />
        ) : (
          <div className="a3-generation-body">
            <section className="a3-generation-evidence">
              <div className="a3-section-label">
                <Brain size={15} />
                <span>选择有作答证据的知识点</span>
                <em>已选 {selectedStates.length}</em>
              </div>
              <div className="a3-evidence-list">
                {knowledge.map((item) => (
                  <label
                    key={item.concept_id}
                    className={
                      selectedConcepts.includes(item.concept_id)
                        ? "selected"
                        : ""
                    }
                  >
                    <input
                      type="checkbox"
                      checked={selectedConcepts.includes(item.concept_id)}
                      disabled={item.evidence_count === 0}
                      onChange={() => toggleConcept(item.concept_id)}
                    />
                    <span>
                      <b>{item.label}</b>
                      <small>
                        掌握度 {Math.round(item.mastery)}% ·{" "}
                        {item.evidence_count} 条证据
                      </small>
                    </span>
                    {item.evidence_count === 0 ? (
                      <em>证据不足</em>
                    ) : (
                      <strong>{Math.round(item.correct_rate)}%</strong>
                    )}
                  </label>
                ))}
              </div>
            </section>
            <section className="a3-generation-settings">
              <div className="a3-section-label">
                <Target size={15} />
                <span>生成设置</span>
              </div>
              <label className="a3-field">
                <span>难度策略</span>
                <select
                  aria-label="难度策略"
                  value={difficulty}
                  onChange={(event) =>
                    setDifficulty(event.target.value as typeof difficulty)
                  }
                >
                  <option value="personalized">个性化匹配</option>
                  <option value="basic">基础</option>
                  <option value="standard">标准</option>
                  <option value="challenge">挑战</option>
                </select>
              </label>
              <label className="a3-field">
                <span>生成模型</span>
                <select
                  aria-label="生成模型"
                  value={profileId}
                  onChange={(event) => setProfileId(event.target.value)}
                >
                  {profiles.map((profile) => (
                    <option
                      key={profile.id}
                      value={profile.id}
                      disabled={!profile.available}
                    >
                      {profile.display_name}
                      {profile.available ? "" : " · 不可用"}
                    </option>
                  ))}
                </select>
              </label>
              <div
                className={`a3-model-state ${selectedProfile?.available ? "available" : "unavailable"}`}
              >
                {selectedProfile?.available ? (
                  <CheckCircle2 size={16} />
                ) : (
                  <AlertTriangle size={16} />
                )}
                <span>
                  {selectedProfile?.available
                    ? "模型凭据与任务能力检查通过"
                    : selectedProfile?.unavailable_reason ||
                      "没有可用于习题生成的模型"}
                </span>
              </div>
              <div className="a3-generation-plan">
                <span>预计题量</span>
                <b>{total}</b>
                <small>每个知识点：2 单选 + 1 判断 + 1 填空</small>
              </div>
            </section>
          </div>
        )}
        <footer>
          <span>
            {busy ? (
              <>
                <LoaderCircle className="spin" size={15} />
                {stage}
              </>
            ) : (
              "生成结果将保留模型运行与题组修订记录"
            )}
          </span>
          <button onClick={onClose}>返回</button>
          <button
            className="primary"
            disabled={
              busy || !selectedProfile?.available || selectedStates.length === 0
            }
            onClick={() => void generate()}
          >
            <Sparkles size={16} />
            生成 {total || ""} 题
          </button>
        </footer>
      </section>
    </div>
  );
}

export default function StudentPracticePage() {
  const api = useApi();
  const { courseId } = useCourse();
  const location = useLocation();
  const { user } = useAuth();
  const setEpoch = useRef(0);
  const actionLock = useRef(false);
  const requestKeys = useRef<Record<string, string>>({});
  const draftKey = "zhixue-draft:practice:" + user!.id + ":" + courseId;
  const preferredTitle = (
    location.state as { questionSetTitle?: string } | null
  )?.questionSetTitle;
  const preferredConceptId = (location.state as { conceptId?: string } | null)
    ?.conceptId;
  const preferredQuestionSetId = (
    location.state as { questionSetId?: string } | null
  )?.questionSetId;
  const [sets, setSets] = useState<QuestionSetSummary[] | null>(null);
  const [activeSet, setActiveSet] = useState<QuestionSetDetail | null>(null);
  const [progress, setProgress] = useState<QuestionSetProgress | null>(null);
  const [activeIndex, setActiveIndex] = useState(0);
  const [answers, setAnswers] = useState<Record<string, AnswerDraft>>({});
  const [hints, setHints] = useState<Record<string, RevealedHint[]>>({});
  const [loadingSet, setLoadingSet] = useState(false);
  const [actionBusy, setActionBusy] = useState("");
  const [error, setError] = useState("");
  const [generationOpen, setGenerationOpen] = useState(false);

  const openSet = useCallback(async (setId: string, conceptId?: string) => {
    const epoch = ++setEpoch.current;
    setActionBusy("");
    actionLock.current = false;
    setLoadingSet(true);
    setError("");
    try {
      const [detail, nextProgress] = await Promise.all([
        api.questionSet(setId),
        api.questionSetProgress(setId),
      ]);
      if (epoch !== setEpoch.current) return;
      setActiveSet(detail);
      setProgress(nextProgress);
      let saved: Record<string, AnswerDraft> = {};
      try {
        saved = JSON.parse(sessionStorage.getItem(draftKey) || "{}");
      } catch {}
      setAnswers(
        Object.fromEntries(
          detail.questions.map((question) => [
            question.id,
            question.attempt_state?.attempt_id
              ? answerDraft(question)
              : (saved[question.id] ?? answerDraft(question)),
          ]),
        ),
      );
      setHints(
        Object.fromEntries(
          detail.questions.map((question) => [
            question.id,
            question.attempt_state?.revealed_hints ?? [],
          ]),
        ),
      );
      const conceptIndex = conceptId
        ? detail.questions.findIndex((question) =>
            question.concepts.some(
              (concept) => concept.concept_id === conceptId,
            ),
          )
        : -1;
      const savedQuestionId = window.sessionStorage.getItem(
        `zhixing-practice-active-question:${setId}`,
      );
      const savedIndex = savedQuestionId
        ? detail.questions.findIndex(
            (question) => question.id === savedQuestionId,
          )
        : -1;
      const pendingIndex = detail.questions.findIndex(
        (question) => !question.attempt_state?.attempt_id,
      );
      const nextIndex =
        conceptIndex >= 0
          ? conceptIndex
          : savedIndex >= 0
            ? savedIndex
            : pendingIndex >= 0
              ? pendingIndex
              : 0;
      setActiveIndex(nextIndex);
      if (detail.questions[nextIndex]) {
        window.sessionStorage.setItem(
          `zhixing-practice-active-question:${setId}`,
          detail.questions[nextIndex].id,
        );
      }
    } catch (reason) {
      if (epoch === setEpoch.current)
        setError(practiceError(reason, "无法打开题组"));
    } finally {
      if (epoch === setEpoch.current) setLoadingSet(false);
    }
  }, []);

  const load = useCallback(async () => {
    setSets(null);
    setActiveSet(null);
    setProgress(null);
    setError("");
    try {
      const response = await api.studentQuestionSets(courseId);
      setSets(response.items);
      const preferred = preferredQuestionSetId
        ? response.items.find((item) => item.id === preferredQuestionSetId)
        : preferredConceptId
          ? response.items.find((item) =>
              item.concepts.some(
                (concept) => concept.concept_id === preferredConceptId,
              ),
            )
          : undefined;
      const initial =
        preferred ??
        response.items.find((x) => x.title === preferredTitle) ??
        response.items.find((item) => item.completed < item.total) ??
        response.items[0];
      if (initial) await openSet(initial.id, preferredConceptId);
    } catch (reason) {
      setError(practiceError(reason, "无法读取练习题组"));
    }
  }, [courseId, openSet, preferredConceptId, preferredQuestionSetId]);

  useEffect(() => {
    void load();
    return () => {
      setEpoch.current++;
    };
  }, [load]);
  useEffect(() => {
    if (Object.keys(answers).length) {
      let saved = {};
      try {
        saved = JSON.parse(sessionStorage.getItem(draftKey) || "{}");
      } catch {}
      sessionStorage.setItem(
        draftKey,
        JSON.stringify({ ...saved, ...answers }),
      );
    }
  }, [answers, draftKey]);

  const question = activeSet?.questions[activeIndex] ?? null;
  const draft = question
    ? (answers[question.id] ?? { selected: [], text: "" })
    : null;
  const score = question?.attempt_state?.score ?? null;
  const progressByQuestion = useMemo(
    () =>
      new Map(progress?.items.map((item) => [item.question_id, item]) ?? []),
    [progress],
  );

  const chooseQuestion = (index: number) => {
    setActiveIndex(index);
    if (activeSet?.id && activeSet.questions[index]) {
      window.sessionStorage.setItem(
        `zhixing-practice-active-question:${activeSet.id}`,
        activeSet.questions[index].id,
      );
    }
  };

  const selectOption = (optionId: string) => {
    if (!question || question.attempt_state?.attempt_id) return;
    setAnswers((current) => {
      const existing = current[question.id] ?? { selected: [], text: "" };
      const selected =
        question.type === "multiple"
          ? existing.selected.includes(optionId)
            ? existing.selected.filter((item) => item !== optionId)
            : [...existing.selected, optionId]
          : [optionId];
      return { ...current, [question.id]: { ...existing, selected } };
    });
  };

  const revealHint = async () => {
    if (!question) return;
    const epoch = setEpoch.current;
    const currentLevel = Math.max(
      question.attempt_state?.hint_level ?? 0,
      hints[question.id]?.length ?? 0,
    );
    const nextLevel = currentLevel + 1;
    if (nextLevel > question.hints_available) {
      actionLock.current = false;
      return;
    }
    setActionBusy(`hint-${question.id}`);
    setError("");
    try {
      const revealed = await api.revealQuestionHint(
        question.id,
        nextLevel,
        (requestKeys.current["hint:" + question.id + ":" + nextLevel] ??=
          crypto.randomUUID()),
      );
      if (epoch !== setEpoch.current) return;
      setHints((current) => ({
        ...current,
        [question.id]: [...(current[question.id] ?? []), revealed],
      }));
      setActiveSet((current) =>
        current
          ? {
              ...current,
              questions: current.questions.map((item) =>
                item.id === question.id && item.attempt_state
                  ? {
                      ...item,
                      attempt_state: {
                        ...item.attempt_state,
                        hint_level: nextLevel,
                      },
                    }
                  : item,
              ),
            }
          : current,
      );
    } catch (reason) {
      setError(practiceError(reason, "提示暂时无法揭示"));
    } finally {
      if (epoch === setEpoch.current) {
        actionLock.current = false;
        setActionBusy("");
      }
    }
  };

  const submit = async () => {
    if (!question || !activeSet || !draft || actionLock.current) return;
    actionLock.current = true;
    const epoch = setEpoch.current;
    setActionBusy(`submit-${question.id}`);
    setError("");
    try {
      const answer =
        question.type === "single" ||
        question.type === "multiple" ||
        question.type === "judgment"
          ? { selected_option_ids: draft.selected }
          : { text: draft.text.trim() };
      const result = await api.submitQuestionAttempt(question.id, {
        idempotency_key: (requestKeys.current[
          "attempt:" + question.id + ":" + JSON.stringify(answer)
        ] ??= crypto.randomUUID()),
        answer,
        expected_revision_id: activeSet.revision_id,
      });
      setActiveSet((current) =>
        current
          ? {
              ...current,
              questions: current.questions.map((item) =>
                item.id === question.id
                  ? {
                      ...item,
                      attempt_state: {
                        attempt_id: result.attempt.id,
                        attempt_no: result.attempt.attempt_no,
                        answer: result.attempt.answer,
                        hint_level: result.attempt.hint_level,
                        status: result.attempt.status,
                        submitted_at: result.attempt.submitted_at,
                        score: result.score,
                        revealed_hints: hints[question.id] ?? [],
                      },
                    }
                  : item,
              ),
            }
          : current,
      );
      const nextProgress = await api.questionSetProgress(activeSet.id);
      setProgress(nextProgress);
      setSets(
        (current) =>
          current?.map((item) =>
            item.id === activeSet.id
              ? {
                  ...item,
                  completed: nextProgress.completed,
                  average_score: nextProgress.average_score,
                }
              : item,
          ) ?? null,
      );
    } catch (reason) {
      setError(practiceError(reason, "答案提交失败"));
    } finally {
      setActionBusy("");
    }
  };

  const acceptGenerated = (generated: QuestionSetDetail) => {
    setGenerationOpen(false);
    setSets((current) =>
      current
        ? [generated, ...current.filter((item) => item.id !== generated.id)]
        : [generated],
    );
    void openSet(generated.id);
  };

  if (error && !sets)
    return <ErrorState message={error} retry={() => void load()} />;
  if (!sets) return <LoadingState label="正在读取练习题组与作答进度…" />;

  const answered = progress?.completed ?? activeSet?.completed ?? 0;
  const hintLevel = question
    ? Math.max(
        question.attempt_state?.hint_level ?? 0,
        hints[question.id]?.length ?? 0,
      )
    : 0;
  const canSubmit = Boolean(
    question &&
      draft &&
      !question.attempt_state?.attempt_id &&
      (question.type === "single" ||
      question.type === "multiple" ||
      question.type === "judgment"
        ? draft.selected.length > 0
        : draft.text.trim().length > 0),
  );

  return (
    <div className="a3-student-page">
      <section className="a3-practice-hero">
        <div>
          <span>
            <Brain size={16} />
            学习证据驱动
          </span>
          <h2>智适练习</h2>
          <p>
            从已发布题组继续作答，按需逐级查看提示；查看评分依据，保留需要教师复核的结果。
          </p>
        </div>
        <div className="a3-practice-hero-actions">
          <button onClick={() => setGenerationOpen(true)}>
            <Sparkles size={16} />
            生成个性化练习
          </button>
          <button
            aria-label="刷新题组"
            title="刷新题组"
            onClick={() => void load()}
          >
            <RefreshCw size={17} />
          </button>
        </div>
      </section>

      {error && (
        <div className="a3-action-error">
          <AlertTriangle size={16} />
          <span>{error}</span>
          <button onClick={() => setError("")}>关闭</button>
        </div>
      )}

      {sets.length === 0 ? (
        <Surface className="a3-empty-state">
          <FileQuestion size={30} />
          <h3>当前课程暂无可用题组</h3>
          <p>可在模型可用时生成个人练习，或等待教师发布经过审核的题组。</p>
          <button onClick={() => setGenerationOpen(true)}>
            <Sparkles size={16} />
            查看生成条件
          </button>
        </Surface>
      ) : (
        <div className="a3-practice-layout">
          <aside className="a3-set-sidebar" aria-label="练习题组">
            <header>
              <span>我的题组</span>
              <em>{sets.length} 组</em>
            </header>
            <div>
              {sets.map((item) => (
                <button
                  key={item.id}
                  className={activeSet?.id === item.id ? "active" : ""}
                  onClick={() => void openSet(item.id)}
                >
                  <span className={`a3-set-status ${item.status}`}>
                    {item.status === "published"
                      ? "已发布"
                      : item.visibility === "private"
                        ? "个人"
                        : "草稿"}
                  </span>
                  <b>{item.title}</b>
                  <small>{setConceptLabels(item)}</small>
                  <div>
                    <i>
                      <em
                        style={{
                          width: `${item.total ? (item.completed / item.total) * 100 : 0}%`,
                        }}
                      />
                    </i>
                    <span>
                      {item.completed}/{item.total}
                    </span>
                  </div>
                </button>
              ))}
            </div>
          </aside>

          <Surface className="a3-practice-workspace">
            {loadingSet || !activeSet || !question ? (
              <LoadingState label="正在恢复题组与作答记录…" />
            ) : (
              <>
                <header className="a3-workspace-header">
                  <div>
                    <span>
                      {activeSet.source_kind === "curated_seed"
                        ? "教师审核题组"
                        : "个性化题组"}{" "}
                      · 修订 {activeSet.revision_no}
                    </span>
                    <h3>{activeSet.title}</h3>
                  </div>
                  <div>
                    <span>
                      <b>{answered}</b> / {activeSet.total} 已完成
                    </span>
                    <i>
                      <em
                        style={{
                          width: `${activeSet.total ? (answered / activeSet.total) * 100 : 0}%`,
                        }}
                      />
                    </i>
                  </div>
                </header>
                <div className="a3-question-layout">
                  <nav className="a3-question-nav" aria-label="题目导航">
                    <span>题目</span>
                    <div>
                      {activeSet.questions.map((item, index) => {
                        const itemProgress = progressByQuestion.get(item.id);
                        const completed =
                          itemProgress?.completed ??
                          Boolean(item.attempt_state?.attempt_id);
                        return (
                          <button
                            key={item.id}
                            className={`${index === activeIndex ? "active" : ""} ${completed ? "completed" : ""}`}
                            aria-label={`第 ${index + 1} 题${completed ? "，已完成" : ""}`}
                            onClick={() => chooseQuestion(index)}
                          >
                            {completed ? <Check size={14} /> : index + 1}
                          </button>
                        );
                      })}
                    </div>
                  </nav>
                  <div className="a3-question-main">
                    <div className="a3-question-meta">
                      <span>{typeLabels[question.type]}</span>
                      <em>
                        第 {activeIndex + 1} / {activeSet.questions.length} 题
                      </em>
                      {question.concepts.map((concept) => (
                        <b key={concept.concept_id}>{concept.label}</b>
                      ))}
                    </div>
                    <h3 className="a3-question-prompt">{question.prompt}</h3>

                    {(question.type === "single" ||
                      question.type === "multiple" ||
                      question.type === "judgment") && (
                      <div className="a3-option-list">
                        {question.options.map((option, optionIndex) => {
                          const selected =
                            draft?.selected.includes(option.id) ?? false;
                          return (
                            <label
                              key={option.id}
                              className={selected ? "selected" : ""}
                            >
                              <input
                                type={
                                  question.type === "multiple"
                                    ? "checkbox"
                                    : "radio"
                                }
                                name={`answer-${question.id}`}
                                checked={selected}
                                disabled={Boolean(
                                  question.attempt_state?.attempt_id,
                                )}
                                onChange={() => selectOption(option.id)}
                              />
                              <span>
                                {String.fromCharCode(65 + optionIndex)}
                              </span>
                              <b>{option.content}</b>
                            </label>
                          );
                        })}
                      </div>
                    )}

                    {question.type === "fill" && (
                      <label className="a3-text-answer compact">
                        <span>填写答案</span>
                        <input
                          aria-label="填写答案"
                          value={draft?.text ?? ""}
                          disabled={Boolean(question.attempt_state?.attempt_id)}
                          onChange={(event) =>
                            setAnswers((current) => ({
                              ...current,
                              [question.id]: {
                                selected: [],
                                text: event.target.value,
                              },
                            }))
                          }
                          placeholder="请输入答案"
                        />
                      </label>
                    )}
                    {(question.type === "short" ||
                      question.type === "scenario") && (
                      <label className="a3-text-answer">
                        <span>组织你的回答</span>
                        <textarea
                          aria-label="组织你的回答"
                          value={draft?.text ?? ""}
                          disabled={Boolean(question.attempt_state?.attempt_id)}
                          onChange={(event) =>
                            setAnswers((current) => ({
                              ...current,
                              [question.id]: {
                                selected: [],
                                text: event.target.value,
                              },
                            }))
                          }
                          placeholder="请输入你的分析与依据"
                        />
                      </label>
                    )}

                    <section className="a3-hint-panel">
                      <header>
                        <div>
                          <Lightbulb size={17} />
                          <span>
                            <b>渐进提示</b>
                            <small>
                              当前已查看 {hintLevel} /{" "}
                              {question.hints_available} 级
                            </small>
                          </span>
                        </div>
                        <button
                          disabled={
                            Boolean(question.attempt_state?.attempt_id) ||
                            hintLevel >= question.hints_available ||
                            actionBusy === `hint-${question.id}`
                          }
                          onClick={() => void revealHint()}
                        >
                          {actionBusy === `hint-${question.id}` ? (
                            <LoaderCircle className="spin" size={15} />
                          ) : (
                            <CircleHelp size={15} />
                          )}
                          {hintLevel >= question.hints_available
                            ? "提示已全部查看"
                            : `查看第 ${hintLevel + 1} 级提示`}
                        </button>
                      </header>
                      {(hints[question.id] ?? []).map((hint) => (
                        <div key={`${hint.question_id}-${hint.level}`}>
                          <span>{hint.level}</span>
                          <p>{hint.content}</p>
                        </div>
                      ))}
                      {hintLevel > (hints[question.id]?.length ?? 0) && (
                        <div>
                          <span>{hintLevel}</span>
                          <p>该级提示已在此前作答中查看。</p>
                        </div>
                      )}
                    </section>

                    {question.attempt_state?.attempt_id && (
                      <section
                        className={`a3-score-panel ${score?.review_status === "needs_review" ? "review" : score?.is_correct ? "correct" : "incorrect"}`}
                      >
                        <span>
                          {score?.review_status === "needs_review" ? (
                            <RefreshCw size={20} />
                          ) : score?.is_correct ? (
                            <CheckCircle2 size={20} />
                          ) : (
                            <AlertTriangle size={20} />
                          )}
                        </span>
                        <div>
                          <b>
                            {score?.review_status === "needs_review"
                              ? "答案已提交，等待教师复核"
                              : score
                                ? `${scorePercent(score.score)} 分`
                                : "答案已提交"}
                          </b>
                          <p>
                            {score
                              ? feedbackText(score) ||
                                (score.review_status === "needs_review"
                                  ? "当前没有可用的主观题评分模型，系统未生成自动评分结论。"
                                  : score.is_correct
                                    ? "回答正确，学习事件已写入学习轨迹并更新学情状态。"
                                    : "本次结果已记录，可结合解析继续巩固。")
                              : "评分状态正在由服务端处理。"}
                          </p>
                          {question.explanation &&
                            score?.review_status !== "needs_review" && (
                              <small>解析：{question.explanation}</small>
                            )}
                        </div>
                      </section>
                    )}
                  </div>
                </div>
                <footer className="a3-practice-footer">
                  <button
                    disabled={activeIndex === 0}
                    onClick={() => chooseQuestion(Math.max(0, activeIndex - 1))}
                  >
                    <ArrowLeft size={16} />
                    上一题
                  </button>
                  <span>
                    {question.attempt_state?.attempt_id
                      ? "本题作答已保存"
                      : "提交后将写入作答、评分与知识点学习事件"}
                  </span>
                  {question.attempt_state?.attempt_id ? (
                    <button
                      className="primary"
                      disabled={activeIndex >= activeSet.questions.length - 1}
                      onClick={() =>
                        chooseQuestion(
                          Math.min(
                            activeSet.questions.length - 1,
                            activeIndex + 1,
                          ),
                        )
                      }
                    >
                      下一题
                      <ArrowRight size={16} />
                    </button>
                  ) : (
                    <button
                      className="primary"
                      disabled={
                        !canSubmit || actionBusy === `submit-${question.id}`
                      }
                      onClick={() => void submit()}
                    >
                      {actionBusy === `submit-${question.id}` ? (
                        <LoaderCircle className="spin" size={16} />
                      ) : (
                        <Send size={16} />
                      )}
                      提交答案
                    </button>
                  )}
                </footer>
              </>
            )}
          </Surface>
        </div>
      )}

      {generationOpen && (
        <StudentGenerationDialog
          courseId={courseId}
          onClose={() => setGenerationOpen(false)}
          onGenerated={acceptGenerated}
        />
      )}
    </div>
  );
}
