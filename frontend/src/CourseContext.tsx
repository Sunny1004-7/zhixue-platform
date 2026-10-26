import {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

const COURSE_KEY = "zhixing-course-id";

type CourseContextValue = {
  courseId: string;
  selectCourse: (courseId: string) => void;
};

const CourseContext = createContext<CourseContextValue | null>(null);

export function CourseProvider({ children }: { children: ReactNode }) {
  const [courseId, setCourseId] = useState(
    () => window.sessionStorage.getItem(COURSE_KEY) ?? "machine-learning",
  );
  const selectCourse = useCallback((nextCourseId: string) => {
    window.sessionStorage.setItem(COURSE_KEY, nextCourseId);
    setCourseId(nextCourseId);
  }, []);
  useEffect(() => {
    const clear = () => setCourseId("machine-learning");
    window.addEventListener("zhixue-session-cleared", clear);
    return () => window.removeEventListener("zhixue-session-cleared", clear);
  }, []);
  const value = useMemo(
    () => ({ courseId, selectCourse }),
    [courseId, selectCourse],
  );
  return (
    <CourseContext.Provider value={value}>{children}</CourseContext.Provider>
  );
}

export function useCourse() {
  const value = useContext(CourseContext);
  if (!value) throw new Error("useCourse 必须在 CourseProvider 中使用");
  return value;
}
