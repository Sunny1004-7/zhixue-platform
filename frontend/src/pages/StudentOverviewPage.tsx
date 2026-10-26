import {
  ArrowRight,
  BookOpenCheck,
  MessageSquareText,
  Target,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../AuthContext";
import { useCourse } from "../CourseContext";
import { useApi } from "../RuntimeContext";
import {
  ErrorState,
  LoadingState,
  Metric,
  EmptyState,
  WeekChart,
} from "../components/Primitives";
import { Modal } from "../components/Dialogs";
import { clamp, knowledgeLabel, number, percent } from "../format";
import type { StudentCourseOverview } from "../types";
export default function StudentOverviewPage() {
  const api = useApi();
  const { user } = useAuth();
  const { courseId } = useCourse();
  const navigate = useNavigate();
  const [data, setData] = useState<StudentCourseOverview | null>(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  const load = useCallback(async () => {
    setError("");
    setData(null);
    try {
      setData(await api.studentOverview(courseId));
    } catch {
      setError("学习状态读取失败，请检查网络后重试。");
    }
  }, [api, courseId]);
  useEffect(() => {
    void load();
  }, [load]);
  if (error) return <ErrorState message={error} retry={() => void load()} />;
  if (!data) return <LoadingState />;
  const weak = data.knowledge_states.filter((x) => x.state === "weak");
  const go = (to: string, conceptId?: string) =>
    navigate("/student/" + to, { state: { courseId, conceptId } });
  const metrics = [
    ["知识掌握度", data.mastery, "%"],
    ["资源完成率", data.resource_completion, "%"],
    ["近30题正确率", data.recent_accuracy, "%"],
    ["连续学习", data.streak, "天"],
  ] as const;
  return (
    <div className="overview-page">
      <section className="page-intro">
        <div>
          <span className="eyebrow">
            {data.course.term} · {data.course.teacher}老师
          </span>
          <h2>{user?.name}，继续探索你的课程。</h2>
          <p>{data.focus_summary}</p>
        </div>
        <div className="intro-actions">
          <button onClick={() => go("resources")}>
            <BookOpenCheck size={17} />
            查看学习资源
          </button>
          <button className="primary" onClick={() => go("practice")}>
            <Target size={17} />
            开始练习
          </button>
        </div>
      </section>
      <section className="metrics-row">
        {metrics.map(([label, m, unit]) => (
          <Metric
            key={label}
            label={label}
            value={unit === "天" ? number(m.value) + " 天" : percent(m.value)}
            note={
              label === "知识掌握度"
                ? "当前有效学习证据"
                : label === "资源完成率"
                  ? "当前课程资源记录"
                  : label === "近30题正确率"
                    ? "按最近作答统计"
                    : "按学习日期统计"
            }
          />
        ))}
      </section>
      <div className="dashboard-columns">
        <section className="surface insight-panel">
          <div className="section-heading">
            <div>
              <h3>知识掌握状态</h3>
              <p>依据作答与有效学习证据估计</p>
            </div>
            <button onClick={() => setOpen(true)}>
              查看全部
              <ArrowRight size={15} />
            </button>
          </div>
          <div className="knowledge-list">
            {data.knowledge_states.slice(0, 6).map((x) => (
              <button
                key={x.concept_id}
                onClick={() => go("resources", x.concept_id)}
              >
                <span>
                  <b>{x.label}</b>
                  <small className={"state-" + x.state}>
                    {knowledgeLabel(x.state, x.evidence_count)}
                  </small>
                </span>
                <i>
                  <em style={{ width: clamp(x.mastery) + "%" }} />
                </i>
                <strong>{percent(x.mastery)}</strong>
                <ArrowRight size={14} />
              </button>
            ))}
          </div>
          {!data.knowledge_states.length && (
            <EmptyState title="还没有知识点学习记录" />
          )}
          <div className="next-step">
            <div>
              <span className="eyebrow">下一步</span>
              <h3>
                {weak.length
                  ? "从需要巩固的知识点继续"
                  : "选择资源，积累新的学习证据"}
              </h3>
              <p>
                {weak.length
                  ? weak
                      .slice(0, 3)
                      .map((x) => x.label)
                      .join("、")
                  : "学习后的变化会按证据更新。"}
              </p>
            </div>
            <button onClick={() => go("tutor", weak[0]?.concept_id)}>
              <MessageSquareText size={17} />
              向智伴提问
            </button>
          </div>
        </section>
        <section className="surface insight-panel">
          <div className="section-heading">
            <div>
              <h3>本周学习投入</h3>
              <p>周一至周日 · 单位：分钟</p>
            </div>
            <span>{number(data.course.weekly_minutes)} 分钟</span>
          </div>
          <WeekChart values={data.weekly_activity} />
          <div className="summary-pairs">
            <span>
              日均 <b>{number(data.daily_average)} 分钟</b>
            </span>
            <span>
              有效学习 <b>{number(data.efficient_sessions)} 次</b>
            </span>
          </div>
          <h3 className="subsection-title">最近学习动态</h3>
          <div className="activity-list">
            {data.recent_activities.slice(0, 4).map((x) => (
              <div key={x.id}>
                <span className="activity-dot" />
                <p>
                  <b>{x.title}</b>
                  <small>{x.detail}</small>
                </p>
              </div>
            ))}
          </div>
          {!data.recent_activities.length && (
            <p className="muted">暂无学习动态</p>
          )}
        </section>
      </div>
      <section className="surface insight-panel">
        <div className="section-heading">
          <h3>最近学习资源</h3>
          <button onClick={() => go("resources")}>
            查看全部
            <ArrowRight size={15} />
          </button>
        </div>
        <div className="recent-resource-list">
          {data.recent_resources.map((x) => (
            <button
              key={x.id}
              onClick={() =>
                navigate(
                  x.resource_type === "question_set"
                    ? "/student/practice"
                    : "/student/resources",
                  {
                    state: {
                      courseId,
                      resourceId: x.id,
                      resourceTitle: x.title,
                      questionSetTitle:
                        x.resource_type === "question_set"
                          ? x.title
                          : undefined,
                      tab:
                        x.resource_type === "learning_video"
                          ? "videos"
                          : "graphs",
                    },
                  },
                )
              }
            >
              <BookOpenCheck size={21} />
              <span>
                <b>{x.title}</b>
                <small>{x.detail}</small>
              </span>
              <ArrowRight size={16} />
            </button>
          ))}
        </div>
        {!data.recent_resources.length && (
          <EmptyState title="暂无最近学习资源" />
        )}
      </section>
      {open && (
        <Modal
          title="完整知识掌握状态"
          onClose={() => setOpen(false)}
          className="knowledge-dialog"
        >
          <p className="muted">
            掌握度综合作答与有效学习证据；证据不足时保留不确定性。
          </p>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>知识点</th>
                  <th>掌握度</th>
                  <th>历史正确率</th>
                  <th>有效证据</th>
                  <th>状态</th>
                  <th>继续学习</th>
                </tr>
              </thead>
              <tbody>
                {data.knowledge_states.map((x) => (
                  <tr key={x.concept_id}>
                    <th>{x.label}</th>
                    <td>{percent(x.mastery)}</td>
                    <td>{percent(x.correct_rate)}</td>
                    <td>{number(x.effective_evidence, 1)}</td>
                    <td>{knowledgeLabel(x.state, x.evidence_count)}</td>
                    <td>
                      <button onClick={() => go("practice", x.concept_id)}>
                        练习
                      </button>
                      <button onClick={() => go("tutor", x.concept_id)}>
                        辅导
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <footer>
            <button onClick={() => setOpen(false)}>完成查看</button>
          </footer>
        </Modal>
      )}
    </div>
  );
}
