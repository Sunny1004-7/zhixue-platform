import { ReactNode } from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../AuthContext';
import type { Role } from '../types';
import { LoadingState } from './Primitives';

export default function ProtectedRoute({ role, children }: { role: Role; children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <main className="boot-screen"><LoadingState label="正在恢复安全会话…" /></main>;
  if (!user || user.role !== role) return <Navigate to="/login" replace />;
  return children;
}
