import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  ExternalLink,
  LoaderCircle,
  Play,
  RefreshCw,
  ThumbsDown,
  ThumbsUp,
  Video,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { ApiError } from '../api';
import { ErrorState, LoadingState } from '../components/Primitives';
import { useCourse } from '../CourseContext';
import { videoApi } from '../videoApi';
import type { VideoProgress, VideoPublication } from '../videoTypes';
import './videoPages.css';

function messageOf(reason: unknown) {
  return reason instanceof ApiError ? reason.message : '无法读取学习视频';
}

function durationLabel(seconds: number | null) {
  if (seconds == null) return '时长未提供';
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(seconds % 60).padStart(2, '0')}`;
}

export default function StudentVideosPage() {
  const { courseId } = useCourse();
  const [resources, setResources] = useState<VideoPublication[] | null>(null);
  const [selectedId, setSelectedId] = useState('');
  const [progress, setProgress] = useState<Record<string, VideoProgress>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const load = useCallback(async () => {
    setError('');
    try {
      const items = await videoApi.resources(courseId);
      setResources(items);
      setSelectedId((current) => items.some((item) => item.id === current) ? current : items[0]?.id ?? '');
      const states = await Promise.all(items.map(async (item) => [item.id, await videoApi.progress(item.id)] as const));
      setProgress(Object.fromEntries(states));
    } catch (reason) { setError(messageOf(reason)); }
  }, [courseId]);

  useEffect(() => { setResources(null); setProgress({}); void load(); }, [load]);
  const selected = useMemo(() => resources?.find((item) => item.id === selectedId) ?? null, [resources, selectedId]);

  const recordOpened = async (publication: VideoPublication) => {
    try {
      const result = await videoApi.event(publication.id, {
        event_type: 'opened', occurred_at: new Date().toISOString(), player_signal: 'page_only',
      }, `video-open-${crypto.randomUUID()}`);
      setProgress((current) => ({ ...current, [publication.id]: result.progress }));
    } catch (reason) { setError(messageOf(reason)); }
  };

  const openOriginal = (publication: VideoPublication) => {
    window.open(publication.resource.canonical_url, '_blank', 'noopener,noreferrer');
    void recordOpened(publication);
  };

  const feedback = async (publication: VideoPublication, value: 'helpful' | 'not_helpful') => {
    setBusy(true); setError('');
    try {
      const result = await videoApi.event(publication.id, {
        event_type: 'feedback', occurred_at: new Date().toISOString(),
        player_signal: 'page_only', feedback: value,
      }, `video-feedback-${crypto.randomUUID()}`);
      setProgress((current) => ({ ...current, [publication.id]: result.progress }));
      setNotice(value === 'helpful' ? '已记录：有帮助' : '已记录：需要更合适的视频');
    } catch (reason) { setError(messageOf(reason)); }
    finally { setBusy(false); }
  };

  if (error && !resources) return <ErrorState message={error} retry={() => void load()} />;
  if (!resources) return <LoadingState label="正在读取教师推送的视频…" />;
  return <div className="vista-page vista-student-page">
    <header className="vista-page-header"><div><span>学习资源 · 视频</span><h2>教师精选视频</h2></div><button className="vista-refresh" disabled={busy} onClick={() => void load()}>{busy ? <LoaderCircle className="spin" size={16} /> : <RefreshCw size={16} />}刷新</button></header>
    {error && <div className="vista-banner error"><AlertTriangle size={16} />{error}</div>}
    {notice && <div className="vista-banner success"><CheckCircle2 size={16} />{notice}</div>}
    {!resources.length ? <div className="vista-empty vista-student-empty"><Video size={27} /><b>当前课程暂无已推送视频</b></div> : <div className="vista-student-workspace">
      <aside className="vista-resource-list">{resources.map((item) => {
        const state = progress[item.id];
        return <button key={item.id} className={selectedId === item.id ? 'active' : ''} onClick={() => setSelectedId(item.id)}>
          <span className="vista-resource-thumb">{item.resource.thumbnail_url ? <img src={item.resource.thumbnail_url} alt="" /> : <Play size={20} />}</span>
          <span><small>{item.audience.mode === 'states' ? '为我定向' : '课程视频'} · {item.resource.evidence_level}</small><b>{item.resource.title}</b><em>{durationLabel(item.resource.duration_seconds)} · {state?.completed ? '已完成' : state?.evidence_scope === 'verified_playback' ? `${Math.round(state.progress_ratio * 100)}%` : '未验证观看进度'}</em></span>
        </button>;
      })}</aside>
      {selected && <section className="vista-student-player">
        <header><div><small>{selected.resource.creator || '发布主体未提供'} · {selected.resource.license_name || '许可信息未提供'}</small><h3>{selected.resource.title}</h3></div><span className={`vista-resource-status ${selected.status}`}>{selected.status === 'active' ? '可用' : selected.status === 'needs_review' ? '待复核' : '暂不可用'}</span></header>
        <div className="vista-player">{selected.status === 'active' && selected.resource.embed_url ? <iframe src={selected.resource.embed_url} title={selected.resource.title} allow="fullscreen; picture-in-picture" referrerPolicy="strict-origin-when-cross-origin" onLoad={() => void recordOpened(selected)} /> : <button onClick={() => openOriginal(selected)}><ExternalLink size={18} />打开平台原页</button>}</div>
        <div className="vista-student-meta"><div><Clock3 size={15} /><span>核验于 {new Date(selected.resource.verified_at).toLocaleString('zh-CN')}</span></div><div><span>学习证据</span><b>{progress[selected.id]?.evidence_scope === 'verified_playback' ? '播放器事件已验证' : '仅记录资源交互'}</b></div><div><span>覆盖知识点</span><b>{selected.resource.matched_topic_ids.length} 个</b></div></div>
        {selected.resource.known_limitations.length > 0 && <div className="vista-limit"><AlertTriangle size={15} />{selected.resource.known_limitations.join('；')}</div>}
        <footer><button onClick={() => openOriginal(selected)}><ExternalLink size={15} />原视频</button><span>这段视频对你有帮助吗？</span><button aria-label="有帮助" disabled={busy} onClick={() => void feedback(selected, 'helpful')}><ThumbsUp size={16} /></button><button aria-label="没有帮助" disabled={busy} onClick={() => void feedback(selected, 'not_helpful')}><ThumbsDown size={16} /></button></footer>
      </section>}
    </div>}
  </div>;
}
