import { ArrowRight, FileQuestion, GitBranch, Video } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useCourse } from "../CourseContext";
import { useApi } from "../RuntimeContext";
import { ApiError } from "../errors";
import {
  ErrorState,
  LoadingState,
  Metric,
  EmptyState,
} from "../components/Primitives";
import { number, percent, clamp } from "../format";
import type { DecisionSnapshot, TeacherCourseOverview } from "../types";
export default function TeacherOverviewPage() {
  const api = useApi();
  const { courseId } = useCourse();
  const navigate = useNavigate();
  const [data, setData] = useState<TeacherCourseOverview | null>(null);
  const [snapshot, setSnapshot] = useState<DecisionSnapshot | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    setData(null);
    setError("");
    try {
      const overview = await api.teacherOverview(courseId);
      let s;
      try {
        s = await api.refreshDecisionSnapshot(courseId);
      } catch (e) {
        if (e instanceof ApiError && e.status === 404)
          s = await api.refreshDecisionSnapshot(courseId);
        else throw e;
      }
      setData(overview);
      setSnapshot(s);
    } catch {
      setError("教学概览读取失败，请重试。");
    }
  }, [api, courseId]);
  useEffect(() => {
    void load();
  }, [load]);
  if (error) return <ErrorState message={error} retry={() => void load()} />;
  if (!data || !snapshot) return <LoadingState />;
  const a = snapshot.aggregate;
  const metrics = [
    ["平均掌握度", data.average_mastery],
    ["近28天正确率", a.average_accuracy ?? data.average_accuracy],
    ["资源完成率", a.average_resource_completion ?? data.resource_completion],
  ] as const;
  return (
    <div className="teacher-overview">
      <section className="page-intro">
        <div>
          <span className="eyebrow">
            {data.class_name} · {data.course.term}
          </span>
          <h2>从班级状态，找到下一步教学安排。</h2>
          <p>综合练习、资源学习与有效辅导记录，查看需要关注的学生。</p>
        </div>
        <span className="snapshot-date">
          更新于 {new Date(snapshot.as_of).toLocaleDateString("zh-CN")}
        </span>
      </section>
      <section className="metrics-row">
        <Metric
          label="课程学生"
          value={number(snapshot.student_count) + " 人"}
        />
        <Metric label="平均掌握度" value={percent(data.average_mastery)} />
        <Metric
          label="需要关注"
          value={snapshot.priority_students.length + " 人"}
        />
        <Metric
          label="近28天人均有效辅导"
          value={number(a.average_effective_tutoring_count, 1) + " 次"}
        />
      </section>
      <div className="dashboard-columns">
        <section className="surface insight-panel">
          <div className="section-heading">
            <h3>班级学习指标</h3>
            <span>当前课程</span>
          </div>
          <div className="indicator-list">
            {metrics.map(([l, v]) => (
              <div key={l}>
                <span>{l}</span>
                <i>
                  <em style={{ width: clamp(v) + "%" }} />
                </i>
                <b>{percent(v)}</b>
              </div>
            ))}
          </div>
          <p className="muted">
            掌握度综合有效证据估计；正确率与资源完成率分别统计。
          </p>
          <div className="teaching-actions">
            <h3>准备教学资源</h3>
            {[
              [
                "知识图谱构建",
                "梳理课程结构与知识关系",
                "/teacher/graphs",
                GitBranch,
              ],
              [
                "智能习题生成",
                "复核题面、答案与提示后发布",
                "/teacher/questions",
                FileQuestion,
              ],
              [
                "学习视频精选",
                "检索公开来源并定向推荐",
                "/teacher/videos",
                Video,
              ],
            ].map(([l, d, to, Icon]) => {
              const I = Icon as typeof GitBranch;
              return (
                <button key={String(to)} onClick={() => navigate(String(to))}>
                  <I size={20} />
                  <span>
                    <b>{String(l)}</b>
                    <small>{String(d)}</small>
                  </span>
                  <ArrowRight size={17} />
                </button>
              );
            })}
          </div>
        </section>
        <section className="surface insight-panel">
          <div className="section-heading">
            <h3>需要教师关注</h3>
            <button onClick={() => navigate("/teacher/students")}>
              查看全部
              <ArrowRight size={15} />
            </button>
          </div>
          <p className="muted">
            关注得分综合练习、正确率、资源完成与辅导记录。
          </p>
          <div className="attention-list">
            {snapshot.priority_students.map((s) => (
              <button
                key={s.student_id}
                onClick={() =>
                  navigate("/teacher/students", {
                    state: { studentId: s.student_id },
                  })
                }
              >
                <span className="identity-avatar">{s.initials}</span>
                <div>
                  <b>{s.student_name}</b>
                  <small>
                    正确率 {percent(s.components.accuracy)} · 有效辅导{" "}
                    {number(s.components.effective_tutoring_count)} 次
                  </small>
                </div>
                <em>{number(s.score, 1)} 分</em>
              </button>
            ))}
          </div>
          {!snapshot.priority_students.length && (
            <EmptyState
              title="当前没有需要优先关注的学生"
              detail="可查看全部学生的知识点状态。"
            />
          )}
        </section>
      </div>
    </div>
  );
}
