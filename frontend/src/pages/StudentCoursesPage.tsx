import { Activity, ArrowRight, BookOpenCheck, Brain, CheckCircle2, Clock3, LogOut, Sparkles, Target, Trophy } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../AuthContext';
import { useCourse } from '../CourseContext';
import { api, ApiError } from '../api';
import { ErrorState, LoadingState, ProgressRing } from '../components/Primitives';
import type { Course, CrossCourseSummary } from '../types';

const accentColor = { indigo: '#656cf6', cyan: '#18a6a0', amber: '#e58b45' };

export default function StudentCoursesPage() {
  const [courses, setCourses] = useState<Course[]>([]);
  const [summary, setSummary] = useState<CrossCourseSummary | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const { user, logout } = useAuth();
  const { selectCourse } = useCourse();
  const navigate = useNavigate();

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [courseRows, overview] = await Promise.all([api.courses(), api.studentSummary()]);
      setCourses(courseRows); setSummary(overview);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : '无法连接课程服务');
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  if (loading) return <main className="course-hub centered"><LoadingState label="正在汇总三门课程…" /></main>;
  if (error || !summary) return <main className="course-hub centered"><ErrorState message={error} retry={() => void load()} /></main>;

  const maxDaily = Math.max(...summary.daily_minutes);
  return (
    <main className="course-hub">
      <header className="hub-header"><div className="login-brand"><span><Sparkles size={20} /></span><div><b>知学智教</b><small>个性化教学平台</small></div></div><div className="hub-profile"><span>{user!.initials}</span><div><b>{user!.name}</b><small>{user!.profile_title}</small></div><button onClick={async () => { await logout(); navigate('/login'); }}><LogOut size={16} />退出</button></div></header>
      <section className="hub-intro"><div><span className="eyebrow"><BookOpenCheck size={14} />我的课程</span><h1>先选择课程，再继续今天的学习。</h1><p>每门课程拥有独立的知识图谱、习题、视频、练习表现和辅导记录。</p></div><div className="hub-summary"><div><span>进行中课程</span><b>{summary.active_courses}</b></div><div><span>本周学习</span><b>{summary.weekly_minutes}<small> 分钟</small></b></div><div><span>待学资源</span><b>{summary.pending_resources}</b></div></div></section>
      <section className="course-grid">{courses.map((course) => <article className={`course-card course-card--${course.accent}`} key={course.id}><div className="course-card-top"><div><span>{course.code} · {course.term}</span><h2>{course.title}</h2><p>{course.teacher}老师</p></div><ProgressRing value={course.mastery ?? 0} label="掌握度" size={86} color={accentColor[course.accent]} /></div><div className="course-goal"><Target size={17} /><div><small>当前目标</small><b>{course.goal}</b></div></div><div className="course-progress"><div><span>课程学习进度</span><b>{course.progress}%</b></div><i><em style={{ width: `${course.progress}%` }} /></i></div><div className="course-meta"><span><Brain size={15} />当前：{course.focus}</span><span><Clock3 size={15} />本周 {course.weekly_minutes} 分钟</span></div><button onClick={() => { selectCourse(course.id); navigate('/student/overview'); }}><BookOpenCheck size={17} />进入课程<ArrowRight size={17} /></button></article>)}</section>
      <section className="cross-course"><div className="cross-heading"><div><span><Activity size={17} /></span><div><b>跨课程学习状态</b><small>汇总三门课程的知识掌握与学习行为</small></div></div><em><CheckCircle2 size={14} />本周状态稳定上升</em></div><div className="cross-body"><div className="overall"><span>综合知识掌握度</span><div><b>{summary.overall_mastery}%</b><em>较上周 +{summary.mastery_delta}%</em></div><i><em style={{ width: `${summary.overall_mastery}%` }} /></i><small>强项：{summary.strong_topics.join('、')} · 待加强：{summary.weak_topics.join('、')}</small></div><div className="compare"><span>三课掌握对比</span>{courses.map((course) => <div key={course.id}><small>{course.short_title}</small><i><em style={{ width: `${course.mastery}%` }} /></i><b>{course.mastery}%</b></div>)}</div><div className="week-trend"><span>近7日学习投入</span><div>{summary.daily_minutes.map((value, index) => <i key={`${value}-${index}`} style={{ height: `${Math.max(18, value / maxDaily * 100)}%` }} className={value === maxDaily ? 'peak' : ''} />)}</div><small>日均 {summary.daily_average} 分钟 · {summary.peak_day}投入最高</small></div><div className="habit"><span><Trophy size={16} />学习表现</span><div><b>{summary.streak_days}天</b><small>连续学习</small></div><div><b>{summary.resource_completion}%</b><small>资源完成率</small></div><p>{summary.preferred_pattern}</p></div></div></section>
    </main>
  );
}
