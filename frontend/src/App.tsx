import { Navigate, Route, Routes } from 'react-router-dom';
import { CourseProvider } from './CourseContext';
import AppShell from './components/AppShell';
import ProtectedRoute from './components/ProtectedRoute';
import LoginPage from './pages/LoginPage';
import StudentCoursesPage from './pages/StudentCoursesPage';
import StudentOverviewPage from './pages/StudentOverviewPage';
import StudentPracticePage from './pages/StudentPracticePage';
import StudentResourcesPage from './pages/StudentResourcesPage';
import StudentTutorPage from './pages/StudentTutorPage';
import TeacherGraphsPage from './pages/TeacherGraphsPage';
import TeacherOverviewPage from './pages/TeacherOverviewPage';
import TeacherQuestionsPage from './pages/TeacherQuestionsPage';
import TeacherStudentsPage from './pages/TeacherStudentsPage';
import TeacherVideosPage from './pages/TeacherVideosPage';

export default function App() {
  return <CourseProvider><Routes>
    <Route path="/" element={<Navigate to="/login" replace />} />
    <Route path="/login" element={<LoginPage />} />
    <Route path="/student/courses" element={<ProtectedRoute role="student"><StudentCoursesPage /></ProtectedRoute>} />
    <Route path="/student" element={<ProtectedRoute role="student"><AppShell /></ProtectedRoute>}>
      <Route index element={<Navigate to="overview" replace />} />
      <Route path="overview" element={<StudentOverviewPage />} />
      <Route path="resources" element={<StudentResourcesPage />} />
      <Route path="practice" element={<StudentPracticePage />} />
      <Route path="tutor" element={<StudentTutorPage />} />
    </Route>
    <Route path="/teacher" element={<ProtectedRoute role="teacher"><AppShell /></ProtectedRoute>}>
      <Route index element={<Navigate to="overview" replace />} />
      <Route path="overview" element={<TeacherOverviewPage />} />
      <Route path="students" element={<TeacherStudentsPage />} />
      <Route path="graphs" element={<TeacherGraphsPage />} />
      <Route path="questions" element={<TeacherQuestionsPage />} />
      <Route path="videos" element={<TeacherVideosPage />} />
    </Route>
    <Route path="*" element={<Navigate to="/login" replace />} />
  </Routes></CourseProvider>;
}
