import { CheckCircle2, ExternalLink, FileText, Filter, GitBranch, Globe2, LoaderCircle, Play, RefreshCw, Search, Send, ShieldCheck, Video, X } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { api, ApiError } from '../api';
import { ErrorState, LoadingState, Surface } from '../components/Primitives';
import { useCourse } from '../CourseContext';
import type { VideoCandidate, VideoSearchJob, VideoSearchSources } from '../types';

type SourceMode = 'graph' | 'records' | 'files' | 'manual';

function requestKey(scope: string) {
  return `${scope}:${crypto.randomUUID()}`;
}

function durationLabel(seconds: number | null) {
  if (seconds == null) return '时长待来源确认';
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(seconds % 60).padStart(2, '0')}`;
}

export default function TeacherVideosPage() {
  const { courseId } = useCourse();
  const [sources, setSources] = useState<VideoSearchSources | null>(null);
  const [sourceMode, setSourceMode] = useState<SourceMode>('records');
  const [topicIds, setTopicIds] = useState<string[]>([]);
  const [graphRevisionId, setGraphRevisionId] = useState('');
  const [assetIds, setAssetIds] = useState<string[]>([]);
  const [manualText, setManualText] = useState('');
  const [intent, setIntent] = useState('面向当前学习阶段，优先选择概念完整、讲解清晰且可核验的教学视频');
  const [job, setJob] = useState<VideoSearchJob | null>(null);
  const [candidates, setCandidates] = useState<VideoCandidate[]>([]);
  const [contentKind, setContentKind] = useState('');
  const [duration, setDuration] = useState('all');
  const [preview, setPreview] = useState<VideoCandidate | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [audienceMode, setAudienceMode] = useState<'all' | 'states'>('all');
  const [audienceStates, setAudienceStates] = useState<Array<'weak' | 'mastered' | 'unseen'>>(['weak']);

  const loadSources = useCallback(async () => {
    setError(''); setSources(null); setCandidates([]); setJob(null);
    try {
      const next = await api.videoSearchSources(courseId);
      setSources(next);
      setTopicIds(next.recorded_topics.slice(0, 2).map((item) => item.concept_id));
    } catch (reason) { setError(reason instanceof ApiError ? reason.message : '无法读取视频检索来源'); }
  }, [courseId]);
  useEffect(() => { void loadSources(); }, [loadSources]);

  const topics = useMemo(() => {
    if (!sources) return [];
    if (sourceMode === 'graph') return sources.graphs.find((item) => item.published_revision_id === graphRevisionId)?.topics ?? [];
    return sources.recorded_topics;
  }, [graphRevisionId, sourceMode, sources]);

  const chooseMode = (mode: SourceMode) => {
    setSourceMode(mode); setTopicIds([]); setAssetIds([]); setGraphRevisionId(''); setManualText(''); setNotice('');
    if (!sources) return;
    if (mode === 'records' || mode === 'files' || mode === 'manual') setTopicIds(sources.recorded_topics.slice(0, 2).map((item) => item.concept_id));
    if (mode === 'graph' && sources.graphs[0]) {
      setGraphRevisionId(sources.graphs[0].published_revision_id);
      setTopicIds(sources.graphs[0].topics.slice(0, 3).map((item) => item.concept_id));
    }
  };

  const toggleTopic = (id: string) => setTopicIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);

  const runSearch = async () => {
    setBusy(true); setError(''); setNotice(''); setCandidates([]);
    try {
      const nextJob = await api.createVideoSearch(courseId, {
        source_mode: sourceMode,
        topic_ids: topicIds,
        graph_revision_id: sourceMode === 'graph' ? graphRevisionId : null,
        asset_ids: sourceMode === 'files' ? assetIds : [],
        raw_text: sourceMode === 'manual' ? manualText : null,
        teaching_intent: intent,
        language: 'zh-CN',
        requested_profile_id: null,
        allow_deterministic_degrade: true,
        max_candidates_per_provider: 12,
      }, requestKey('video-search'));
      setJob(nextJob);
      const rows = await api.videoCandidates(nextJob.id);
      setCandidates(rows);
      if (!rows.length) setNotice('公开来源未返回通过安全与元数据核验的视频，请调整知识点或教学意图后重试。');
    } catch (reason) { setError(reason instanceof ApiError ? reason.message : '视频检索失败'); }
    finally { setBusy(false); }
  };

  const applyFilters = async () => {
    if (!job) return;
    setBusy(true);
    const range = duration === 'short' ? { maxDuration: 600 } : duration === 'medium' ? { minDuration: 601, maxDuration: 1800 } : duration === 'long' ? { minDuration: 1801 } : {};
    try { setCandidates(await api.videoCandidates(job.id, { ...range, contentKind: contentKind || undefined })); }
    catch (reason) { setError(reason instanceof ApiError ? reason.message : '筛选失败'); }
    finally { setBusy(false); }
  };

  const openPreview = async (candidate: VideoCandidate) => {
    setError('');
    try {
      await api.previewVideoCandidate(candidate.id, 'embedded_preview', requestKey('video-preview'));
      setCandidates((rows) => rows.map((item) => item.id === candidate.id ? { ...item, previewed: true } : item));
      setPreview({ ...candidate, previewed: true });
    } catch (reason) { setError(reason instanceof ApiError ? reason.message : '无法记录预览'); }
  };

  const openOriginal = async (candidate: VideoCandidate) => {
    const popup = window.open(candidate.canonical_url, '_blank', 'noopener,noreferrer');
    try {
      await api.previewVideoCandidate(candidate.id, 'original_page_opened', requestKey('video-original'));
      setCandidates((rows) => rows.map((item) => item.id === candidate.id ? { ...item, previewed: true } : item));
    } catch (reason) {
      if (!popup) setError(reason instanceof ApiError ? reason.message : '无法打开视频来源');
    }
  };

  const publish = async (candidate: VideoCandidate) => {
    if (audienceMode === 'states' && audienceStates.length === 0) {
      setError('按学习状态发布至少选择一个状态。');
      return;
    }
    setBusy(true); setNotice(''); setError('');
    try {
      const selectedConceptIds = candidate.matched_topic_ids.length ? candidate.matched_topic_ids : topicIds;
      const draft = await api.previewAudience(courseId, candidate.id, {
        resource_type: 'video',
        resource_id: candidate.id,
        resource_version: 1,
        audience_mode: audienceMode === 'all' ? 'class' : 'concept_directed',
        selected_concept_ids: selectedConceptIds,
        selected_states: audienceMode === 'states' ? audienceStates : [],
        teacher_selected_student_ids: [],
      });
      const acknowledgeWarnings = draft.warnings_require_confirmation
        ? window.confirm('接收者预览包含重复或频控警告，确认仍要发布吗？')
        : false;
      if (draft.warnings_require_confirmation && !acknowledgeWarnings) {
        setNotice('已保留接收者预览，教师取消了本次发布。');
        return;
      }
      const result = await api.publishAudience(draft.id, draft.version, acknowledgeWarnings, requestKey('audience-video-publish'));
      setNotice(`《${candidate.title}》已按${audienceMode === 'all' ? '全班' : '学习状态'}发布给 ${result.recipient_count} 名学生。`);
    } catch (reason) { setError(reason instanceof ApiError ? reason.message : '视频发布失败'); }
    finally { setBusy(false); }
  };

  if (error && !sources) return <ErrorState message={error} retry={() => void loadSources()} />;
  if (!sources) return <LoadingState label="正在读取课程知识来源…" />;

  return <div className="teacher-videos-page">
    <Surface className="video-search-builder">
      <header><div><span><Globe2 size={15} />公开网络来源</span><h2>教学视频搜索与核验</h2></div><span className="trust-chip"><ShieldCheck size={15} />链接、来源与元数据逐项核验</span></header>
      <div className="source-mode-tabs">
        {([['graph', GitBranch, '知识图谱'], ['records', CheckCircle2, '系统记录'], ['files', FileText, '教学文件'], ['manual', Search, '手动输入']] as const).map(([mode, Icon, label]) => <button key={mode} className={sourceMode === mode ? 'active' : ''} onClick={() => chooseMode(mode)}><Icon size={16} />{label}</button>)}
      </div>

      {sourceMode === 'graph' && <label className="video-source-select"><span>已发布图谱</span><select value={graphRevisionId} onChange={(event) => { const revision = event.target.value; setGraphRevisionId(revision); setTopicIds(sources.graphs.find((item) => item.published_revision_id === revision)?.topics.slice(0, 3).map((item) => item.concept_id) ?? []); }}>{sources.graphs.map((graph) => <option value={graph.published_revision_id} key={graph.graph_id}>{graph.title} · {graph.topics.length} 个知识点</option>)}</select></label>}
      {sourceMode === 'files' && <div className="video-asset-list">{sources.parsed_assets.length ? sources.parsed_assets.map((asset) => <label key={asset.asset_id}><input type="checkbox" checked={assetIds.includes(asset.asset_id)} onChange={() => setAssetIds((current) => current.includes(asset.asset_id) ? current.filter((id) => id !== asset.asset_id) : [...current, asset.asset_id])} /><FileText size={16} /><span><b>{asset.original_name}</b><small>{asset.parsed_title}</small></span></label>) : <p>当前课程暂无已解析教学文件，请先在知识图谱构建中上传并完成解析。</p>}</div>}
      {sourceMode === 'manual' && <label className="manual-video-input"><span>知识点说明</span><textarea value={manualText} onChange={(event) => setManualText(event.target.value)} placeholder="输入需要检索的课程概念、学习阶段或案例方向" /></label>}

      <div className="topic-chip-picker">{topics.map((topic) => <button key={topic.concept_id} className={topicIds.includes(topic.concept_id) ? 'active' : ''} onClick={() => toggleTopic(topic.concept_id)}><span>{topic.label}</span>{topic.correct_rate != null && <small>{Math.round(topic.correct_rate)}%</small>}</button>)}</div>
      <div className="video-intent-row"><label><span>教学意图</span><input value={intent} onChange={(event) => setIntent(event.target.value)} /></label><button className="primary-action" disabled={busy || !topicIds.length || (sourceMode === 'files' && !assetIds.length) || (sourceMode === 'manual' && !manualText.trim())} onClick={() => void runSearch()}>{busy ? <LoaderCircle className="spin" size={17} /> : <Search size={17} />}搜索并核验</button></div>
    </Surface>

    {job && <section className="video-job-status"><div><b>{job.status === 'completed' ? '检索完成' : job.status === 'partial' ? '部分来源可用' : job.status}</b><span>{job.candidate_count} 个通过核验的候选</span></div>{job.provider_statuses.map((provider) => <span key={provider.provider} className={`provider-${provider.status}`}>{provider.provider} · {provider.accepted_count}/{provider.discovered_count}</span>)}</section>}

    {job && <Surface className="video-results">
      <div className="video-result-toolbar"><div><span><Filter size={15} />结果筛选</span><select value={duration} onChange={(event) => setDuration(event.target.value)}><option value="all">全部时长</option><option value="short">10分钟内</option><option value="medium">10-30分钟</option><option value="long">30分钟以上</option></select><select value={contentKind} onChange={(event) => setContentKind(event.target.value)}><option value="">全部类型</option><option value="lecture">讲座</option><option value="tutorial">教程</option><option value="case">案例</option><option value="video">视频</option></select><button onClick={() => void applyFilters()}><RefreshCw size={15} />应用</button></div><span>{candidates.length} 条结果</span></div>
      <div className="video-candidate-list">{candidates.map((candidate) => <article key={candidate.id}>
        <button className="video-thumbnail" aria-label={`预览${candidate.title}`} onClick={() => void openPreview(candidate)}>{candidate.thumbnail_url ? <img src={candidate.thumbnail_url} alt="" referrerPolicy="no-referrer" /> : <Video size={34} />}<span><Play size={18} /></span><small>{durationLabel(candidate.duration_seconds)}</small></button>
        <div className="video-candidate-copy"><div><span>{candidate.provider}</span><em>{candidate.evidence_level}</em><small>综合 {Math.round(candidate.scores.final * 100)}</small></div><h3>{candidate.title}</h3><p>{candidate.description || '来源未提供简介，发布前请打开原始页面核验内容。'}</p><footer><span>{candidate.creator ?? '作者待来源确认'}</span>{candidate.license_name && <span>{candidate.license_name}</span>}<span>{candidate.matched_topic_ids.length} 个匹配知识点</span></footer></div>
       <div className="video-candidate-actions"><button onClick={() => void openPreview(candidate)}><Play size={15} />预览</button><button onClick={() => void openOriginal(candidate)}><ExternalLink size={15} />原始页面</button><button className="publish" disabled={busy || (candidate.preview_required && !candidate.previewed) || (audienceMode === 'states' && audienceStates.length === 0)} title={candidate.preview_required && !candidate.previewed ? '发布前需完成预览' : audienceMode === 'states' && audienceStates.length === 0 ? '至少选择一个学习状态' : '预览接收者并发布视频'} onClick={() => void publish(candidate)}><Send size={15} />发布</button></div>
      </article>)}</div>
      {!candidates.length && <div className="empty-result"><Globe2 size={28} /><p>{notice || '当前筛选条件下暂无通过核验的候选。'}</p></div>}
    </Surface>}

    {job && <section className="video-audience-bar"><span>发布范围</span><button className={audienceMode === 'all' ? 'active' : ''} onClick={() => setAudienceMode('all')}>全班</button><button className={audienceMode === 'states' ? 'active' : ''} onClick={() => setAudienceMode('states')}>按学习状态</button>{audienceMode === 'states' && (['weak', 'mastered', 'unseen'] as const).map((state) => <label key={state}><input type="checkbox" checked={audienceStates.includes(state)} onChange={() => setAudienceStates((current) => current.includes(state) ? current.filter((item) => item !== state) : [...current, state])} />{{ weak: '薄弱', mastered: '掌握', unseen: '未接触' }[state]}</label>)}</section>}
    {notice && <div className="success-notice">{notice}</div>}{error && <div className="inline-error">{error}</div>}

    {preview && <div className="dialog-backdrop" onMouseDown={() => setPreview(null)}><section className="video-preview-dialog" role="dialog" aria-label={preview.title} onMouseDown={(event) => event.stopPropagation()}><header><div><span>{preview.provider} · {preview.evidence_level}</span><h3>{preview.title}</h3></div><button aria-label="关闭预览" onClick={() => setPreview(null)}><X size={18} /></button></header><div>{preview.embed_url ? <iframe src={preview.embed_url} title={preview.title} allow="fullscreen; picture-in-picture" /> : <div className="video-preview-fallback"><Video size={42} /><p>该来源未提供可嵌入播放器，请在原始页面核验。</p><button onClick={() => void openOriginal(preview)}><ExternalLink size={16} />打开原始页面</button></div>}</div><footer><span>核验范围：{preview.verified_scope.join('、') || '页面可访问性'}</span>{preview.uncertainty_reason && <span>{preview.uncertainty_reason}</span>}</footer></section></div>}
  </div>;
}
