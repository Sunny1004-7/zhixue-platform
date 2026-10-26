import { BookOpenCheck, FileQuestion, GitBranch, TrendingUp, UsersRound, Video } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useCourse } from '../CourseContext';
import { api, ApiError } from '../api';
import { ErrorState, LoadingState, Surface } from '../components/Primitives';
import type { DecisionSnapshot, TeacherCourseOverview } from '../types';

export default function TeacherOverviewPage() {
  const { courseId } = useCourse();
  const [data, setData] = useState<TeacherCourseOverview | null>(null);
  const [snapshot, setSnapshot] = useState<DecisionSnapshot | null>(null);
  const [error, setError] = useState('');
  const navigate = useNavigate();
  const load = useCallback(async () => {
    setData(null); setError('');
    try {
      setData(await api.teacherOverview(courseId));
      try {
        setSnapshot(await api.decisionOverview(courseId));
      } catch (reason) {
        if (reason instanceof ApiError && reason.status === 404) setSnapshot(await api.refreshDecisionSnapshot(courseId));
        else throw reason;
      }
    }
    catch (reason) { setError(reason instanceof ApiError ? reason.message : '无法读取教学概览'); }
  }, [courseId]);
  useEffect(() => { void load(); }, [load]);
  if (error) return <ErrorState message={error} retry={() => void load()} />;
  if (!data) return <LoadingState label="正在汇总班级学习证据…" />;
  const aggregate = snapshot?.aggregate ?? {};
  const overviewMetrics = [
    ['平均掌握度', data.average_mastery],
    ['近 28 天正确率', Number(aggregate.average_accuracy ?? data.average_accuracy)],
    ['资源完成率', Number(aggregate.average_resource_completion ?? data.resource_completion)],
    ['平均有效辅导', Math.min(100, Number(aggregate.average_effective_tutoring_count ?? 0) / 6 * 100)],
  ] as const;
  const priority = snapshot?.priority_students ?? [];
  return <div className="teacher-overview"><section className="teacher-hero"><div><span>{data.class_name} · {data.course.term}</span><h2>教学概览</h2><p>班级整体学习状态已根据最新练习、资源学习与有效辅导证据更新。</p></div><div><button onClick={() => navigate('/teacher/graphs')}><GitBranch size={17} />构建知识图谱</button><button onClick={() => navigate('/teacher/questions')}><FileQuestion size={17} />生成习题组</button><button onClick={() => navigate('/teacher/videos')}><Video size={17} />精选学习视频</button></div></section><section className="teacher-stat-grid"><Surface><span><UsersRound size={20} /></span><div><small>课程学生</small><b>{data.student_count}<em>人</em></b></div></Surface><Surface><span><TrendingUp size={20} /></span><div><small>平均掌握度</small><b>{data.average_mastery}%</b></div></Surface><Surface><span><FileQuestion size={20} /></span><div><small>近28天正确率</small><b>{data.average_accuracy}%</b></div></Surface><Surface><span><BookOpenCheck size={20} /></span><div><small>资源完成率</small><b>{data.resource_completion}%</b></div></Surface></section><section className="teacher-panels"><Surface><div className="section-heading"><h3>班级学习指标</h3><button onClick={() => navigate('/teacher/students')}>查看全部学生</button></div><div className="teacher-placeholder-bars">{overviewMetrics.map(([label, value]) => <div key={label}><span>{label}</span><i><em style={{ width: `${Math.max(0, Math.min(100, Number(value)))}%` }} /></i><b>{Math.round(Number(value))}{label === '平均有效辅导' ? '%' : '%'}</b></div>)}</div></Surface><Surface><div className="section-heading"><h3>需要教师关注</h3><span>快照识别 {priority.length || data.priority_student_count} 人</span></div><div className="attention-list">{priority.length ? priority.map((student) => <button key={student.student_id} onClick={() => navigate('/teacher/students')}><span>{student.initials}</span><div><b>{student.student_name}</b><small>重点关注得分 {student.score.toFixed(1)} · 正确率 {Math.round(student.components.accuracy)}%</small></div><em>{student.score.toFixed(0)}分</em></button>) : <div className="empty-result"><p>当前快照没有需要优先关注的学生。</p></div>}</div></Surface></section></div>;
}
