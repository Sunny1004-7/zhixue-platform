import {
  AlertTriangle,
  ArrowDownAZ,
  ArrowDownWideNarrow,
  ArrowUpNarrowWide,
  BookOpenCheck,
  FileQuestion,
  GitBranch,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  Video,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { knowledgeLabel, percent } from "../format";
import { ApiError } from "../errors";
import { useApi } from "../RuntimeContext";
import { ErrorState, LoadingState, Surface } from "../components/Primitives";
import { useCourse } from "../CourseContext";
import type {
  DecisionSnapshot,
  StudentAttention,
  StudentLearningState,
} from "../types";

type SortMode = "score_desc" | "score_asc" | "name";

function requestKey(scope: string) {
  return `${scope}:${crypto.randomUUID()}`;
}

export default function TeacherStudentsPage() {
  const api = useApi();
  const { courseId } = useCourse();
  const [snapshot, setSnapshot] = useState<DecisionSnapshot | null>(null);
  const [students, setStudents] = useState<StudentAttention[] | null>(null);
  const location = useLocation();
  const [selectedId, setSelectedId] = useState(
    (location.state as { studentId?: string } | null)?.studentId ?? "",
  );
  const loadEpoch = useRef(0);
  const snapshotEpoch = useRef(0);
  const jobEpoch = useRef(0);
  const [detail, setDetail] = useState<StudentLearningState | null>(null);
  const [sort, setSort] = useState<SortMode>("score_asc");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("");
  const [composing, setComposing] = useState(false);
  const [rosterLoading, setRosterLoading] = useState(false);
  const [rosterError, setRosterError] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [jobMessage, setJobMessage] = useState("");

  const load = useCallback(
    async (refresh = false) => {
      const epoch = ++snapshotEpoch.current;
      setError("");
      if (refresh) setBusy(true);
      else setStudents(null);
      try {
        let nextSnapshot: DecisionSnapshot;
        try {
          nextSnapshot = await api.refreshDecisionSnapshot(courseId);
        } catch (reason) {
          // A new course has no snapshot yet; initialize it on first access so the page is usable.
          if (!refresh && reason instanceof ApiError && reason.status === 404) {
            nextSnapshot = await api.refreshDecisionSnapshot(courseId);
          } else {
            throw reason;
          }
        }
        if (epoch !== snapshotEpoch.current) return;
        setSnapshot(nextSnapshot);
      } catch (reason) {
        if (epoch === snapshotEpoch.current)
          setError(
            reason instanceof ApiError
              ? reason.message
              : "无法读取当前课程学情",
          );
      } finally {
        if (epoch === snapshotEpoch.current) setBusy(false);
      }
    },
    [api, courseId],
  );

  useEffect(() => {
    void load();
    return () => {
      snapshotEpoch.current++;
    };
  }, [load]);
  useEffect(() => {
    if (composing) return;
    const timer = window.setTimeout(() => setFilter(query), 180);
    return () => window.clearTimeout(timer);
  }, [query, composing]);
  const loadRoster = useCallback(async () => {
    if (!snapshot) return;
    const epoch = ++loadEpoch.current;
    setRosterLoading(true);
    setRosterError("");
    try {
      const list = await api.courseStudents(courseId, sort, filter);
      if (epoch !== loadEpoch.current) return;
      setStudents(list.items);
      setSelectedId((current) =>
        list.items.some((item) => item.student_id === current)
          ? current
          : (list.items[0]?.student_id ?? current),
      );
    } catch (reason) {
      if (epoch === loadEpoch.current)
        setRosterError(
          reason instanceof ApiError
            ? reason.message
            : "学生名单读取失败，请重试。",
        );
    } finally {
      if (epoch === loadEpoch.current) setRosterLoading(false);
    }
  }, [api, courseId, snapshot, sort, filter]);
  useEffect(() => {
    void loadRoster();
    return () => {
      loadEpoch.current++;
    };
  }, [loadRoster]);
  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    setDetail(null);
    let live = true;
    api
      .studentLearningState(courseId, selectedId)
      .then((value) => {
        if (live) setDetail(value);
      })
      .catch((reason) => {
        if (!live) return;
        setError(
          reason instanceof ApiError ? reason.message : "无法读取学生知识状态",
        );
      });
    return () => {
      live = false;
    };
  }, [courseId, selectedId, snapshot?.snapshot_hash]);

  const selected = useMemo(
    () => students?.find((item) => item.student_id === selectedId) ?? null,
    [selectedId, students],
  );

  const createPersonalized = async (
    resourceType: "graph" | "question_set" | "video",
  ) => {
    if (!detail) return;
    const epoch = ++jobEpoch.current;
    const concepts = detail.weak_concept_ids.length
      ? detail.weak_concept_ids.slice(0, 3)
      : detail.concepts.slice(0, 1).map((item) => item.concept_id);
    setBusy(true);
    setJobMessage("");
    try {
      const job = (await api.personalizedResourceJob(
        courseId,
        detail.student_id,
        {
          resource_type: resourceType,
          concept_ids: concepts,
          idempotency_key: requestKey(`student-resource:${resourceType}`),
          request_payload: {
            source: "teacher_student_state",
            snapshot_id: detail.snapshot_id,
          },
        },
      )) as { status?: string; upstream_status?: { message?: string } };
      if (epoch !== jobEpoch.current) return;
      setJobMessage(
        job.upstream_status?.message ??
          `个性化资源任务状态：${job.status ?? "已创建"}`,
      );
    } catch (reason) {
      setJobMessage(
        reason instanceof ApiError ? reason.message : "资源任务创建失败",
      );
    } finally {
      setBusy(false);
    }
  };

  if (error && !students)
    return <ErrorState message={error} retry={() => void load()} />;
  if (!snapshot) return <LoadingState label="正在计算课程学情快照…" />;

  return (
    <div className="teacher-students-page">
      <section className="decision-strip">
        <div>
          <span>
            <Sparkles size={15} />
            重点关注
          </span>
          <strong>{snapshot.priority_students.length}</strong>
          <small>名学生</small>
        </div>
        <div>
          <span>班级人数</span>
          <strong>{snapshot.student_count}</strong>
          <small>当前课程</small>
        </div>
        <div>
          <span>快照时间</span>
          <strong>
            {new Date(snapshot.as_of).toLocaleDateString("zh-CN")}
          </strong>
          <small>当前课程</small>
        </div>
        <button disabled={busy} onClick={() => void load(true)}>
          <RefreshCw size={16} className={busy ? "spin" : ""} />
          刷新快照
        </button>
      </section>

      <div className="student-state-layout">
        <Surface className="student-roster-panel">
          <div className="student-roster-toolbar">
            <label>
              <Search size={15} />
              <input
                aria-label="搜索学生"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onCompositionStart={() => setComposing(true)}
                onCompositionEnd={() => setComposing(false)}
                placeholder="搜索学生"
              />
            </label>
            <div className="sort-segment" aria-label="学生排序">
              <button
                title="关注得分降序"
                className={sort === "score_desc" ? "active" : ""}
                onClick={() => setSort("score_desc")}
              >
                <ArrowDownWideNarrow size={16} />
              </button>
              <button
                title="关注得分升序"
                className={sort === "score_asc" ? "active" : ""}
                onClick={() => setSort("score_asc")}
              >
                <ArrowUpNarrowWide size={16} />
              </button>
              <button
                title="姓名排序"
                className={sort === "name" ? "active" : ""}
                onClick={() => setSort("name")}
              >
                <ArrowDownAZ size={16} />
              </button>
            </div>
          </div>
          {rosterError && (
            <ErrorState message={rosterError} retry={() => void loadRoster()} />
          )}
          {rosterLoading && <LoadingState label="正在读取学生名单…" />}
          <div className="student-roster" role="list" aria-busy={rosterLoading}>
            {(students ?? []).map((student) => (
              <button
                key={student.student_id}
                role="listitem"
                className={student.student_id === selectedId ? "active" : ""}
                onClick={() => {
                  jobEpoch.current++;
                  setJobMessage("");
                  setSelectedId(student.student_id);
                }}
              >
                <span className="student-avatar">{student.initials}</span>
                <span>
                  <b>{student.student_name}</b>
                  <small>
                    练习 {student.components.practice_count} 次 · 得分率{" "}
                    {student.components.accuracy_samples === 0 ? "—" : percent(student.components.accuracy)}
                  </small>
                </span>
                <em className={student.priority ? "priority" : ""}>
                  {student.score.toFixed(1)}
                </em>
              </button>
            ))}
          </div>
        </Surface>

        <Surface className="student-detail-panel">
          {!students?.length ? (
            <div className="empty-result">
              <h3>当前筛选没有学生</h3>
              <p>请调整姓名或排序条件。</p>
            </div>
          ) : !detail || !selected ? (
            <LoadingState label="正在读取知识状态…" />
          ) : (
            <>
              <header className="student-detail-header">
                <div>
                  <span className="student-avatar large">
                    {selected.initials}
                  </span>
                  <div>
                    <small>关注排序 #{detail.rank}</small>
                    <h2>{detail.student_name}</h2>
                    <p>证据置信度 {Math.round(detail.confidence * 100)}%</p>
                  </div>
                </div>
                {selected.priority && (
                  <span className="priority-badge">
                    <AlertTriangle size={15} />
                    重点关注
                  </span>
                )}
              </header>

              <div className="attention-formula" aria-label="重点关注得分构成">
                {[
                  ["练习量", detail.components.practice_score, "25%"],
                  ["得分率", detail.components.accuracy_score, "30%"],
                  ["资源完成", detail.components.resource_score, "25%"],
                  ["有效辅导", detail.components.tutoring_score, "20%"],
                ].map(([label, value, weight]) => (
                  <div key={label as string}>
                    <span>
                      <b>{label}</b>
                      <small>权重 {weight}</small>
                    </span>
                    <i>
                      <em style={{ width: `${Number(value)}%` }} />
                    </i>
                    <strong>{Math.round(Number(value))}</strong>
                  </div>
                ))}
              </div>

              <section className="concept-state-section">
                <div className="section-heading">
                  <div>
                    <span>
                      {
                        detail.concepts.filter((x) => x.evidence_count > 0)
                          .length
                      }{" "}
                      个有作答记录知识点
                    </span>
                    <h3>逐知识点学习状态</h3>
                  </div>
                  <span className="privacy-chip">
                    <ShieldCheck size={14} />
                    不包含辅导对话正文
                  </span>
                </div>
                <div className="table-scroll">
                  <div className="concept-state-table">
                    <div className="concept-state-row head">
                      <span>知识点</span>
                      <span>状态</span>
                      <span>掌握度</span>
                      <span>证据</span>
                      <span>30天趋势</span>
                    </div>
                    {detail.concepts.map((concept) => (
                      <div
                        className="concept-state-row"
                        key={concept.concept_id}
                      >
                        <span>
                          <b>{concept.label}</b>
                          <small>
                            {concept.low_evidence
                              ? "证据不足"
                              : `置信度 ${Math.round(concept.confidence * 100)}%`}
                          </small>
                        </span>
                        <span>
                          <em className={`state-${concept.state}`}>
                            {knowledgeLabel(
                              concept.state,
                              concept.evidence_count,
                            )}
                          </em>
                        </span>
                        <span>
                          <i>
                            <em style={{ width: `${concept.mastery}%` }} />
                          </i>
                          {Math.round(concept.mastery)}%
                        </span>
                        <span>{concept.evidence_count} 条</span>
                        <span
                          className={
                            concept.trend_30d >= 0 ? "trend-up" : "trend-down"
                          }
                        >
                          {concept.trend_30d >= 0 ? "+" : ""}
                          {concept.trend_30d.toFixed(1)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </section>

              <footer className="personalized-resource-actions">
                <div>
                  <small>为该生构建</small>
                  <b>个性化学习资源</b>
                </div>
                <button
                  disabled={busy}
                  onClick={() => void createPersonalized("graph")}
                >
                  <GitBranch size={16} />
                  知识图谱
                </button>
                <button
                  disabled={busy}
                  onClick={() => void createPersonalized("question_set")}
                >
                  <FileQuestion size={16} />
                  习题
                </button>
                <button
                  disabled={busy}
                  onClick={() => void createPersonalized("video")}
                >
                  <Video size={16} />
                  视频
                </button>
                {jobMessage && (
                  <p>
                    <BookOpenCheck size={15} />
                    {jobMessage}
                  </p>
                )}
              </footer>
            </>
          )}
        </Surface>
      </div>
      {error && <div className="inline-error">{error}</div>}
    </div>
  );
}
