import BrandGlyph from "./BrandGlyph";
import { useDialogs } from "./Dialogs";
import {
  BookOpenCheck,
  ChevronDown,
  FileQuestion,
  GitBranch,
  LayoutDashboard,
  LogOut,
  Menu,
  MessageSquareText,
  UsersRound,
  Video,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../AuthContext";
import { useCourse } from "../CourseContext";
import { useApi } from "../RuntimeContext";
import type { Course } from "../types";
export const navByRole = {
  student: [
    ["学习概览", "/student/overview", LayoutDashboard],
    ["学习资源", "/student/resources", BookOpenCheck],
    ["智适练习", "/student/practice", FileQuestion],
    ["智伴辅导", "/student/tutor", MessageSquareText],
  ],
  teacher: [
    ["教学概览", "/teacher/overview", LayoutDashboard],
    ["学生学情", "/teacher/students", UsersRound],
    ["知识图谱构建", "/teacher/graphs", GitBranch],
    ["智能习题生成", "/teacher/questions", FileQuestion],
    ["学习视频精选", "/teacher/videos", Video],
  ],
} as const;
export function Brand() {
  return (
    <div className="product-brand">
      <BrandGlyph />
      <div>
        <b>知学智教</b>
        <small>个性化教学平台</small>
      </div>
    </div>
  );
}
export default function AppShell() {
  const api = useApi();
  const dialogs = useDialogs();
  const { user, logout } = useAuth();
  const { courseId, selectCourse } = useCourse();
  const navigate = useNavigate();
  const location = useLocation();
  const [courses, setCourses] = useState<Course[]>([]);
  const [drawer, setDrawer] = useState(false);
  const [menu, setMenu] = useState(false);
  const [error, setError] = useState("");
  const role = user!.role;
  const active = navByRole[role].find((x) => x[1] === location.pathname);
  const course = courses.find((x) => x.id === courseId);
  useEffect(() => {
    let live = true;
    api
      .courses()
      .then((items) => {
        if (!live) return;
        setCourses(items);
        if (items.length && !items.some((x) => x.id === courseId))
          selectCourse(items[0].id);
      })
      .catch(() => {
        if (live) setError("课程列表读取失败，请刷新页面重试。");
      });
    return () => {
      live = false;
    };
  }, [api, courseId, selectCourse]);
  useEffect(() => {
    setDrawer(false);
    setMenu(false);
  }, [location.pathname]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setDrawer(false);
        setMenu(false);
      }
    };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, []);
  const exit = async () => {
    if (!(await dialogs.canLeave())) return;
    await logout();
    navigate("/login", { replace: true });
  };
  return (
    <>
      <a className="skip-link" href="#main-content">
        跳转到主要内容
      </a>
      <div className={"app-shell app-shell--" + role}>
        {drawer && (
          <button
            className="nav-scrim"
            aria-label="关闭导航"
            onClick={() => setDrawer(false)}
          />
        )}
        <aside
          role={drawer ? "dialog" : undefined}
          aria-modal={drawer ? true : undefined}
          className={"sidebar" + (drawer ? " is-open" : "")}
          aria-label={role === "student" ? "学生导航" : "教师导航"}
        >
          <div className="sidebar-brand">
            <Brand />
            <button
              className="mobile-only"
              aria-label="关闭导航"
              onClick={() => setDrawer(false)}
            >
              <X size={20} />
            </button>
          </div>
          <div className="role-label">
            {role === "student" ? "学生学习空间" : "教师教学空间"}
          </div>
          <label className="course-picker">
            <span>当前课程</span>
            <select
              aria-label="当前课程"
              value={course?.id ?? ""}
              onChange={async (e) => {
                const next = e.target.value;
                if (await dialogs.canLeave()) selectCourse(next);
              }}
            >
              {!courses.length && <option value="">暂无课程</option>}
              {courses.map((x) => (
                <option key={x.id} value={x.id}>
                  {x.title}
                </option>
              ))}
            </select>
          </label>
          {role === "student" && (
            <NavLink
              className="all-courses"
              to="/student/courses"
              onClick={async (e) => {
                if(e.button!==0||e.ctrlKey||e.metaKey||e.shiftKey||e.altKey)return;
                e.preventDefault();
                if (await dialogs.canLeave()) navigate("/student/courses");
              }}
            >
              <BookOpenCheck size={16} />
              全部课程
            </NavLink>
          )}
          <nav>
            {navByRole[role].map(([label, to, Icon]) => (
              <NavLink
                key={to}
                to={to}
                onClick={async (e) => {
                  if(e.button!==0||e.ctrlKey||e.metaKey||e.shiftKey||e.altKey)return;
                e.preventDefault();
                  if (await dialogs.canLeave()) navigate(to);
                }}
                className={({ isActive }) => (isActive ? "active" : "")}
              >
                <Icon size={19} />
                {label}
              </NavLink>
            ))}
          </nav>
          <div className="sidebar-foot">
            <span className="identity-avatar">{user!.initials}</span>
            <div>
              <b>{user!.name}</b>
              <small>{role === "student" ? "学生" : "教师"}</small>
            </div>
            <button
              aria-label="退出当前账号"
              title="退出当前账号"
              onClick={() => void exit()}
            >
              <LogOut size={18} />
            </button>
          </div>
        </aside>
        <section className="workspace">
          <header className="topbar">
            <button
              className="mobile-only"
              aria-label="打开导航"
              aria-expanded={drawer}
              onClick={() => setDrawer(true)}
            >
              <Menu size={22} />
            </button>
            <div className="page-location">
              <span>
                {course?.title ?? "课程空间"}
                <ChevronDown size={12} />
                {role === "student" ? "学习" : "教学"}
              </span>
              <h1>{active?.[0] ?? "课程空间"}</h1>
            </div>
            <div className="topbar-actions">
              <span className="term-label">{course?.term}</span>
              <button
                className="profile-button"
                aria-expanded={menu}
                onClick={() => setMenu(!menu)}
              >
                <span>{user!.initials}</span>
                <b>{user!.name}</b>
                <ChevronDown size={14} />
              </button>
              {menu && (
                <div className="profile-menu">
                  <p>{user!.email}</p>
                  <button onClick={() => void exit()}>
                    <LogOut size={16} />
                    退出登录
                  </button>
                </div>
              )}
            </div>
          </header>
          {error && (
            <p className="inline-error" role="alert">
              {error}
            </p>
          )}
          <main
            id="main-content"
            tabIndex={-1}
            className="workspace-main"
            key={user!.id + ":" + courseId}
          >
            <Outlet />
          </main>
        </section>
      </div>
    </>
  );
}
