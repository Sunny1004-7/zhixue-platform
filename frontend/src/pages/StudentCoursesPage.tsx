import { ArrowRight, BookOpenCheck, LogOut } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../AuthContext";
import { useCourse } from "../CourseContext";
import { useApi } from "../RuntimeContext";
import { Brand } from "../components/AppShell";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  Metric,
  ProgressRing,
  WeekChart,
} from "../components/Primitives";
import { delta, number, percent, clamp } from "../format";
import type { Course, CrossCourseSummary } from "../types";
export default function StudentCoursesPage() {
  const api = useApi();
  const { user, logout } = useAuth();
  const { selectCourse } = useCourse();
  const navigate = useNavigate();
  const [courses, setCourses] = useState<Course[] | null>(null);
  const [summary, setSummary] = useState<CrossCourseSummary | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    setError("");
    setCourses(null);
    try {
      const [c, s] = await Promise.all([api.courses(), api.studentSummary()]);
      setCourses(c);
      setSummary(s);
    } catch {
      setError("课程读取失败，请检查网络后重试。");
    }
  }, [api]);
  useEffect(() => {
    void load();
  }, [load]);
  return (
    <main className="course-hub">
      <header className="hub-header">
        <Brand />
        <div className="hub-profile">
          <span>{user?.name} · 学生</span>
          <button
            onClick={async () => {
              await logout();
              navigate("/login", { replace: true });
            }}
          >
            <LogOut size={16} />
            退出
          </button>
        </div>
      </header>
      {error ? (
        <ErrorState message={error} retry={() => void load()} />
      ) : !courses || !summary ? (
        <LoadingState label="正在汇总课程…" />
      ) : (
        <>
          <section className="hub-intro">
            <div>
              <span className="eyebrow">我的课程 / LEARNING SPACE</span>
              <h1>{user?.name}，从一门课程开始。</h1>
              <p>在知识结构中找到方向，用练习与辅导推进学习。</p>
            </div>
            <BookOpenCheck size={42} />
          </section>
          <section className="metrics-row">
            <Metric label="已加入课程" value={courses.length + " 门"} />
            <Metric
              label="本周学习"
              value={number(summary.weekly_minutes) + " 分钟"}
            />
            <Metric
              label="待学资源"
              value={number(summary.pending_resources) + " 项"}
            />
            <Metric
              label="总体掌握度"
              value={percent(summary.overall_mastery)}
              note={delta(summary.mastery_delta)}
            />
          </section>
          <section className="course-grid">
            {courses.map((c) => (
              <article
                className={"course-card course-card--" + c.accent}
                key={c.id}
              >
                <div className="course-card-top">
                  <div>
                    <span>
                      {c.code} · {c.term}
                    </span>
                    <h2>{c.title}</h2>
                    <p>{c.teacher}老师</p>
                  </div>
                  <ProgressRing value={c.mastery} label="掌握度" size={86} />
                </div>
                <div className="course-goal">
                  <small>当前学习目标</small>
                  <p>{c.goal || "进入课程查看学习安排"}</p>
                </div>
                <div className="course-progress">
                  <span>
                    资源学习进度 <b>{percent(c.progress)}</b>
                  </span>
                  <i>
                    <em style={{ width: clamp(c.progress) + "%" }} />
                  </i>
                </div>
                <div className="course-meta">
                  <span>{c.focus || "等待学习记录"}</span>
                  <span>本周 {number(c.weekly_minutes)} 分钟</span>
                </div>
                <button
                  className="primary"
                  onClick={() => {
                    selectCourse(c.id);
                    navigate("/student/overview");
                  }}
                >
                  进入课程
                  <ArrowRight size={17} />
                </button>
              </article>
            ))}
          </section>
          {!courses.length && (
            <EmptyState
              title="还没有加入课程"
              detail="请联系任课教师确认课程安排。"
            />
          )}
          <section className="hub-bottom">
            <div>
              <h2>本周学习节奏</h2>
              <p>所有已加入课程 · 单位：分钟</p>
              <WeekChart values={summary.daily_minutes} />
            </div>
            <div>
              <span className="eyebrow">学习状态</span>
              <h2>让每次学习留下依据</h2>
              <p>
                知识掌握度依据作答和有效学习证据估计。可在课程内查看知识点状态，选择合适的练习与资源。
              </p>
              <div className="summary-pairs">
                <span>
                  资源完成率 <b>{percent(summary.resource_completion)}</b>
                </span>
                <span>
                  连续学习 <b>{number(summary.streak_days)} 天</b>
                </span>
              </div>
            </div>
          </section>
        </>
      )}
    </main>
  );
}
