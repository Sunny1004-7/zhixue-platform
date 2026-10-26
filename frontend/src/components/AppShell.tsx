import {
  Bell,
  BookOpenCheck,
  ChevronDown,
  FileQuestion,
  GitBranch,
  LayoutDashboard,
  LogOut,
  MessageSquareText,
  ShieldCheck,
  Sparkles,
  UsersRound,
  Video,
} from 'lucide-react';
import { useEffect, useState } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../AuthContext';
import { useCourse } from '../CourseContext';
import { api } from '../api';
import type { Course } from '../types';

const navByRole = {
  student: [
    ['学习概览', '/student/overview', LayoutDashboard],
    ['学习资源', '/student/resources', BookOpenCheck],
    ['智适练习', '/student/practice', FileQuestion],
    ['智伴辅导', '/student/tutor', MessageSquareText],
  ],
  teacher: [
    ['教学概览', '/teacher/overview', LayoutDashboard],
    ['学生学情', '/teacher/students', UsersRound],
    ['知识图谱构建', '/teacher/graphs', GitBranch],
    ['智能习题生成', '/teacher/questions', FileQuestion],
    ['学习视频精选', '/teacher/videos', Video],
  ],
} as const;

const pageTitle: Record<string, [string, string]> = {
  '/student/overview': ['学习概览', '整体状态、课程进展与近期动态'],
  '/student/resources': ['学习资源', '知识图谱、习题与学习视频'],
  '/student/practice': ['智适练习', '题组、渐进提示、作答与学习反馈'],
  '/student/tutor': ['智伴辅导', '多策略辅导、长期学习记忆与教学经验'],
  '/teacher/overview': ['教学概览', '班级学习进展与资源使用'],
  '/teacher/students': ['学生学情', '重点关注识别、知识状态与个性化干预'],
  '/teacher/graphs': ['知识图谱构建', '新建、更新、审核与发布课程知识结构'],
  '/teacher/questions': ['智能习题生成', '蓝图编译、教师复核与题组发布'],
  '/teacher/videos': ['学习视频精选', '公开来源检索、核验、推荐与定向发布'],
};

export default function AppShell() {
  const { user, logout } = useAuth();
  const { courseId, selectCourse } = useCourse();
  const navigate = useNavigate();
  const location = useLocation();
  const [courses, setCourses] = useState<Course[]>([]);
  const [menuOpen, setMenuOpen] = useState(false);
  const role = user!.role;
  const currentCourse = courses.find((item) => item.id === courseId) ?? courses[0];
  const [title, eyebrow] = pageTitle[location.pathname] ?? ['功能建设中', '相关服务将按教学流程逐步接入'];

  useEffect(() => {
    api.courses().then((items) => {
      setCourses(items);
      if (items.length && !items.some((item) => item.id === courseId)) selectCourse(items[0].id);
    }).catch(() => undefined);
  }, [courseId, selectCourse]);

  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };

  return (
    <div className={`app-shell app-shell--${role}`}>
      <aside className="sidebar">
        <div className="brand"><span><Sparkles size={18} /></span><div><b>知学智教</b><small>大模型驱动的个性化教学平台</small></div></div>
        {role === 'student' ? (
          <button className="course-switch" onClick={() => navigate('/student/courses')}>
            <BookOpenCheck size={18} /><span><small>当前课程</small><b>{currentCourse?.title ?? '正在读取'}</b></span><ChevronDown size={16} />
          </button>
        ) : (
          <div className="course-switch course-switch--select">
            <BookOpenCheck size={18} />
            <label><small>当前课程</small><select value={currentCourse?.id ?? ''} onChange={(event) => selectCourse(event.target.value)}>{courses.map((course) => <option key={course.id} value={course.id}>{course.title}</option>)}</select></label>
          </div>
        )}
        <nav>
          {navByRole[role].map(([label, path, Icon]) => (
            <NavLink key={path} to={path} className={({ isActive }) => isActive ? 'active' : ''}><Icon size={19} /><span>{label}</span></NavLink>
          ))}
        </nav>
        <button className="logout-button" onClick={handleLogout}><LogOut size={18} />退出当前账号</button>
      </aside>
      <section className="workspace">
        <header className="topbar">
          <div><span>{eyebrow}</span><h1>{currentCourse ? `${currentCourse.title} · ${title}` : title}</h1></div>
          <div className="topbar-actions">
            <span className="trust-chip"><ShieldCheck size={16} />{role === 'student' ? '历史记录可控' : '智能构建有据可查'}</span>
            <button className="icon-button" aria-label="通知"><Bell size={18} /><i /></button>
            <button className="profile-button" onClick={() => setMenuOpen((value) => !value)}><span>{user!.initials}</span><div><b>{user!.name}</b><small>{user!.profile_title}</small></div><ChevronDown size={15} /></button>
            {menuOpen && <div className="profile-menu"><b>{user!.email}</b><button onClick={handleLogout}><LogOut size={15} />退出登录</button></div>}
          </div>
        </header>
        <main className="workspace-main"><Outlet /></main>
      </section>
    </div>
  );
}
