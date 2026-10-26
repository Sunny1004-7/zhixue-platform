import { ArrowRight, BarChart3, BookOpenCheck, Brain, CheckCircle2, Clock3, FileQuestion, Flame, GitBranch, MessageSquareText, Target, TrendingUp, Video, X } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useCourse } from '../CourseContext';
import { api, ApiError } from '../api';
import { ErrorState, LoadingState, ProgressRing, Sparkline, Surface } from '../components/Primitives';
import type { StudentCourseOverview } from '../types';

const iconByResource = { knowledge_graph: GitBranch, question_set: FileQuestion, learning_video: Video };
const colorByAccent = { indigo: '#7d84ff', cyan: '#18a6a0', amber: '#e58b45' };

export default function StudentOverviewPage() {
  const { courseId } = useCourse();
  const [data, setData] = useState<StudentCourseOverview | null>(null);
  const [error, setError] = useState('');
  const [masteryOpen, setMasteryOpen] = useState(false);
  const navigate = useNavigate();
  const load = useCallback(async () => {
    setData(null); setError('');
    try { setData(await api.studentOverview(courseId)); }
    catch (reason) { setError(reason instanceof ApiError ? reason.message : '无法连接学习状态服务'); }
  }, [courseId]);
  useEffect(() => { void load(); }, [load]);
  const weak = useMemo(() => data ? [...data.knowledge_states].sort((a, b) => a.mastery - b.mastery).slice(0, 3) : [], [data]);

  if (error) return <ErrorState message={error} retry={() => void load()} />;
  if (!data) return <LoadingState />;
  const course = data.course;
  const maxWeekly = Math.max(...data.weekly_activity);
  const cards = [
    ['知识掌握度', data.mastery, Brain, 'indigo'],
    ['课程资源完成率', data.resource_completion, BookOpenCheck, 'mint'],
    ['近30题正确率', data.recent_accuracy, Target, 'amber'],
    ['连续学习', data.streak, Flame, 'rose'],
  ] as const;
  return (
    <div className="overview-page">
      <section className={`overview-hero overview-hero--${course.accent}`}><div><span className="eyebrow">{course.term} · {course.teacher}老师</span><small>下午好，林知夏</small><h2>今天继续学习“{course.focus}”</h2><p>{data.focus_summary}</p><div className="hero-actions"><button className="resource" onClick={() => navigate('/student/resources')}><BookOpenCheck size={17} />继续学习资源</button><button className="practice" onClick={() => navigate('/student/practice')}><Target size={17} />开始智适练习</button><button className="tutor" onClick={() => navigate('/student/tutor')}><MessageSquareText size={17} />开始智伴辅导</button></div></div><div className="hero-status"><ProgressRing value={course.mastery ?? 0} label="课程掌握度" size={126} color={colorByAccent[course.accent]} /><div><span>课程学习进度</span><b>{course.progress}%</b><i><em style={{ width: `${course.progress}%` }} /></i><small>本周已学习 {course.weekly_minutes} 分钟</small></div></div></section>
      <section className="stat-grid">{cards.map(([label, metric, Icon, tone]) => <Surface className="stat-card" key={label}><span className={`stat-icon ${tone}`}><Icon size={19} /></span><div><small>{label}</small><b>{Math.round(metric.value)}{label === '连续学习' ? <em>天</em> : '%'}</b><span className="delta"><TrendingUp size={13} />{metric.delta}</span></div><Sparkline values={metric.trend} color={tone === 'mint' ? '#20bfa9' : tone === 'amber' ? '#f49b57' : tone === 'rose' ? '#df6f87' : '#6268f6'} /></Surface>)}</section>
      <section className="overview-grid">
        <Surface className="mastery-panel"><div className="section-heading"><h3>知识掌握状态</h3><div><button onClick={() => navigate('/student/practice')}><Target size={14} />针对薄弱项练习</button><button onClick={() => navigate('/student/tutor')}><MessageSquareText size={14} />针对薄弱项辅导</button><button onClick={() => setMasteryOpen(true)}><BarChart3 size={14} />查看完整状态</button></div></div><div className="mastery-summary"><div><strong>{Math.round(course.mastery ?? 0)}%</strong><span>整体掌握稳定提升</span></div><div><TrendingUp size={17} /><span>当前最需要巩固</span><p>{weak.map((item) => <b key={item.concept_id}>{item.label}<em>{Math.round(item.mastery)}%</em></b>)}</p></div></div><div className="mastery-bars">{data.knowledge_states.slice(0, 6).map((item) => <div key={item.concept_id}><span>{item.label}</span><i><em style={{ width: `${item.mastery}%` }} /></i><b>{Math.round(item.mastery)}%</b></div>)}</div></Surface>
        <Surface className="weekly-panel"><div className="section-heading"><h3>本周学习投入</h3><span>{course.weekly_minutes} 分钟</span></div><div className="weekly-bars">{data.weekly_activity.map((value, index) => <div key={`${value}-${index}`}><span style={{ height: `${Math.max(14, value / maxWeekly * 100)}%` }}>{value === maxWeekly && <em>{value}</em>}</span><small>{['一','二','三','四','五','六','日'][index]}</small></div>)}</div><div className="weekly-meta"><span><Clock3 size={15} />日均 {data.daily_average} 分钟</span><span><BarChart3 size={15} />高效学习 {data.efficient_sessions} 次</span></div></Surface>
        <Surface className="resources-panel"><div className="section-heading"><h3>最近学习资源</h3><button onClick={() => navigate('/student/resources')}>查看全部 <ArrowRight size={14} /></button></div>{data.recent_resources.map((resource, index) => { const Icon = iconByResource[resource.resource_type]; return <button className={index === 0 ? 'resource-row current' : 'resource-row'} key={resource.id} onClick={() => navigate('/student/resources')}><span><Icon size={18} /></span><div><b>{resource.title}</b><small>{resource.detail}</small></div><em>继续学习 <ArrowRight size={14} /></em></button>; })}</Surface>
        <Surface className="activity-panel"><div className="section-heading"><h3>最近学习动态</h3></div>{data.recent_activities.map((activity) => <div className="activity-row" key={activity.id}><span className={activity.activity_type}>{activity.activity_type === 'result' ? <CheckCircle2 size={16} /> : activity.activity_type === 'learn' ? <MessageSquareText size={16} /> : <Target size={16} />}</span><p><b>{activity.title}</b><small>{activity.detail}</small></p></div>)}</Surface>
      </section>
      {masteryOpen && <div className="dialog-backdrop" onMouseDown={() => setMasteryOpen(false)}><section className="mastery-dialog" role="dialog" aria-modal="true" aria-label="完整知识掌握状态" onMouseDown={(event) => event.stopPropagation()}><header><div><span>知学智教 · EGLT学习状态</span><h3>{course.title} · 完整知识掌握状态</h3><p>掌握度由作答与有效学习证据综合估计；历史正确率单独展示。</p></div><button aria-label="关闭" onClick={() => setMasteryOpen(false)}><X size={18} /></button></header><div className="mastery-dialog-head"><span>知识点</span><span>掌握度</span><span>历史正确率</span><span>有效证据</span><span>状态</span></div><div className="mastery-dialog-list">{data.knowledge_states.map((item) => <div key={item.concept_id}><b>{item.label}</b><span><i><em style={{ width: `${item.mastery}%` }} /></i>{Math.round(item.mastery)}%</span><span>{Math.round(item.correct_rate)}%</span><span>{item.effective_evidence.toFixed(1)}</span><em className={item.state}>{item.state === 'mastered' ? '已掌握' : item.state === 'weak' ? '薄弱' : '未接触'}</em></div>)}</div><footer><span>状态不确定性已计入分类；证据不足时优先标记为“未接触”。</span><button onClick={() => setMasteryOpen(false)}>完成查看</button></footer></section></div>}
    </div>
  );
}
