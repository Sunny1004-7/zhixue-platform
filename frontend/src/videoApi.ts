import { ApiError } from './api';
import type {
  VideoAudience,
  VideoCandidate,
  VideoPlayerEvent,
  VideoProgress,
  VideoPublication,
  VideoSearchJob,
  VideoSearchSources,
  VideoSourceMode,
} from './videoTypes';

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000/api/v1';
const TOKEN_KEY = 'zhixing-access-token';

async function videoRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (typeof init.body === 'string') headers.set('Content-Type', 'application/json');
  const token = window.sessionStorage.getItem(TOKEN_KEY);
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!response.ok) {
    let message = '视频服务请求失败';
    let code: string | null = null;
    try {
      const payload = await response.json() as { detail?: string | { code?: string; message?: string } };
      if (typeof payload.detail === 'string') message = payload.detail;
      else if (payload.detail) {
        message = payload.detail.message ?? message;
        code = payload.detail.code ?? null;
      }
    } catch {
      // Keep a privacy-safe fallback for non-JSON provider failures.
    }
    throw new ApiError(response.status, message, code);
  }
  return response.json() as Promise<T>;
}

function idempotent(method: 'POST', payload: unknown, key: string): RequestInit {
  return {
    method,
    headers: { 'Idempotency-Key': key },
    body: JSON.stringify(payload),
  };
}

export const videoApi = {
  sources: (courseId: string) => videoRequest<VideoSearchSources>(`/teacher/courses/${courseId}/video-search-sources`),
  search: (courseId: string, payload: {
    source_mode: VideoSourceMode;
    topic_ids: string[];
    graph_revision_id?: string;
    asset_ids?: string[];
    raw_text?: string;
    teaching_intent?: string;
    max_candidates_per_provider?: number;
  }, key: string) => videoRequest<VideoSearchJob>(`/courses/${courseId}/video-search-jobs`, idempotent('POST', payload, key)),
  job: (jobId: string) => videoRequest<VideoSearchJob>(`/video-search-jobs/${jobId}`),
  candidates: (jobId: string, filters: { minDuration?: number; maxDuration?: number; contentKind?: string } = {}) => {
    const query = new URLSearchParams();
    if (filters.minDuration != null) query.set('min_duration', String(filters.minDuration));
    if (filters.maxDuration != null) query.set('max_duration', String(filters.maxDuration));
    if (filters.contentKind) query.set('content_kind', filters.contentKind);
    const suffix = query.size ? `?${query.toString()}` : '';
    return videoRequest<VideoCandidate[]>(`/video-search-jobs/${jobId}/candidates${suffix}`);
  },
  candidate: (candidateId: string) => videoRequest<VideoCandidate>(`/video-candidates/${candidateId}`),
  preview: (candidateId: string, action: 'embedded_preview' | 'original_page_opened', key: string) => videoRequest(`/video-candidates/${candidateId}/preview-events`, idempotent('POST', { action }, key)),
  recheck: (candidateId: string, key: string) => videoRequest(`/video-candidates/${candidateId}/recheck`, idempotent('POST', {}, key)),
  publish: (candidateId: string, audience: VideoAudience, key: string) => videoRequest<VideoPublication>('/video-publications', idempotent('POST', { candidate_id: candidateId, audience }, key)),
  resources: (courseId: string) => videoRequest<VideoPublication[]>(`/courses/${courseId}/resources?type=video`),
  publication: (publicationId: string) => videoRequest<VideoPublication>(`/video-publications/${publicationId}`),
  progress: (publicationId: string) => videoRequest<VideoProgress>(`/video-publications/${publicationId}/progress`),
  event: (publicationId: string, payload: VideoPlayerEvent, key: string) => videoRequest<{ progress: VideoProgress }>(`/video-publications/${publicationId}/events`, idempotent('POST', payload, key)),
};
