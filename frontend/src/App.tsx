import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { CourseProvider } from "./CourseContext";
import AppShell from "./components/AppShell";
import ProtectedRoute from "./components/ProtectedRoute";
import LoginPage from "./pages/LoginPage";
import { LoadingState } from "./components/Primitives";
const StudentCourses = lazy(() => import("./pages/StudentCoursesPage"));
const StudentOverview = lazy(() => import("./pages/StudentOverviewPage"));
const StudentResources = lazy(() => import("./pages/StudentResourcesPage"));
const StudentPractice = lazy(() => import("./pages/StudentPracticePage"));
const StudentTutor = lazy(() => import("./pages/StudentTutorPage"));
const TeacherOverview = lazy(() => import("./pages/TeacherOverviewPage"));
const TeacherStudents = lazy(() => import("./pages/TeacherStudentsPage"));
const TeacherGraphs = lazy(() => import("./pages/TeacherGraphsPage"));
const TeacherQuestions = lazy(() => import("./pages/TeacherQuestionsPage"));
const TeacherVideos = lazy(() => import("./pages/TeacherVideosPage"));
export default function App() {
  return (
    <CourseProvider>
      <Suspense fallback={<LoadingState label="正在打开课程空间…" />}>
        <Routes>
          <Route path="/" element={<Navigate to="/login" replace />} />
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/student/courses"
            element={
              <ProtectedRoute role="student">
                <StudentCourses />
              </ProtectedRoute>
            }
          />
          <Route
            path="/student"
            element={
              <ProtectedRoute role="student">
                <AppShell />
              </ProtectedRoute>
            }
          >
            <Route index element={<Navigate to="overview" replace />} />
            <Route path="overview" element={<StudentOverview />} />
            <Route path="resources" element={<StudentResources />} />
            <Route path="practice" element={<StudentPractice />} />
            <Route path="tutor" element={<StudentTutor />} />
          </Route>
          <Route
            path="/teacher"
            element={
              <ProtectedRoute role="teacher">
                <AppShell />
              </ProtectedRoute>
            }
          >
            <Route index element={<Navigate to="overview" replace />} />
            <Route path="overview" element={<TeacherOverview />} />
            <Route path="students" element={<TeacherStudents />} />
            <Route path="graphs" element={<TeacherGraphs />} />
            <Route path="questions" element={<TeacherQuestions />} />
            <Route path="videos" element={<TeacherVideos />} />
          </Route>
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </Suspense>
    </CourseProvider>
  );
}
