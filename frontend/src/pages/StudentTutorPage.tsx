import { BrainCircuit, Check, ChevronRight, FilePlus2, History, Lightbulb, LoaderCircle, MemoryStick, MessageSquarePlus, Mic, Network, Pencil, Plus, Search, Send, Sparkles, Trash2, Volume2, X } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { api, ApiError } from '../api';
import { ErrorState, LoadingState } from '../components/Primitives';
import { useCourse } from '../CourseContext';
import type { ModelProfile, TutorConversation, TutorConversationItem, TutorExperience, TutorMemory, TutorMessage, TutorMode } from '../types';

const modes: Array<{ id: TutorMode; label: string; note: string }> = [
  { id: 'adaptive', label: '自适应选择', note: '依据问题与学习状态路由' },
  { id: 'coach', label: '启发引导', note: '通过追问形成推理链' },
  { id: 'visualize', label: '可视化解释', note: '输出可访问的结构图示' },
  { id: 'practice', label: '即时练习', note: '接入当前课程题组' },
  { id: 'research', label: '联网研证', note: '给出可核验来源' },
  { id: 'explain', label: '类比拆解', note: '分步解释抽象概念' },
];

type WorkspaceTab = 'chat' | 'memory' | 'experience';
type SpeechResultEvent = { results: ArrayLike<{ 0: { transcript: string } }> };
type Recognition = { lang: string; interimResults: boolean; start: () => void; onresult: ((event: SpeechResultEvent) => void) | null; onerror: (() => void) | null; onend: (() => void) | null };
type RecognitionCtor = new () => Recognition;

function clientId() { return `turn:${crypto.randomUUID()}`; }

function VisualExplanation({ visual }: { visual: Record<string, unknown> }) {
  const nodes = Array.isArray(visual.nodes) ? visual.nodes as Array<{ id?: string; label?: string; detail?: string }> : [];
  const edges = Array.isArray(visual.edges) ? visual.edges as Array<{ source?: string; target?: string; label?: string }> : [];
  return <figure className="tutor-visual" aria-label={String(visual.alt_text ?? visual.title ?? '辅导图示')}>
    <figcaption>{String(visual.title ?? '结构图示')}</figcaption>
    <div>{nodes.map((node, index) => <div key={node.id ?? index}><span>{index + 1}</span><b>{node.label ?? '节点'}</b>{node.detail && <small>{node.detail}</small>}</div>)}</div>
    {edges.length > 0 && <p>{edges.map((edge) => `${edge.source ?? ''} → ${edge.target ?? ''}${edge.label ? `（${edge.label}）` : ''}`).join(' · ')}</p>}
  </figure>;
}

function ChatMessage({ message }: { message: TutorMessage }) {
  return <article className={`tutor-message tutor-message--${message.role}`}>
    <span>{message.role === 'assistant' ? <Sparkles size={16} /> : '我'}</span>
    <div>{message.title && <h3>{message.title}</h3>}<p>{message.body}</p>
      {message.visual && <VisualExplanation visual={message.visual} />}
      {message.inline_practice && <section className="tutor-inline-practice"><b>即时练习</b><p>{String(message.inline_practice.prompt ?? '请进入智适练习完成当前题目。')}</p>{Array.isArray(message.inline_practice.options) && <div>{(message.inline_practice.options as Array<{ id?: string; content?: string }>).map((option, index) => <span key={option.id ?? index}>{String.fromCharCode(65 + index)}. {option.content ?? ''}</span>)}</div>}<button type="button" onClick={() => { window.location.href = '/student/practice'; }}>进入智适练习</button></section>}
      {message.citations.length > 0 && <footer>{message.citations.map((citation, index) => citation.url ? <a key={`${citation.url}-${index}`} href={citation.url} target="_blank" rel="noreferrer"><Network size={14} />{citation.label ?? `来源 ${index + 1}`}</a> : null)}</footer>}
    </div>
  </article>;
}

export default function StudentTutorPage() {
  const { courseId } = useCourse();
  const location = useLocation();
  const conceptId = typeof (location.state as { conceptId?: unknown } | null)?.conceptId === 'string'
    ? String((location.state as { conceptId: string }).conceptId)
    : null;
  const [profiles, setProfiles] = useState<ModelProfile[]>([]);
  const [conversations, setConversations] = useState<TutorConversationItem[] | null>(null);
  const [conversation, setConversation] = useState<TutorConversation | null>(null);
  const [mode, setMode] = useState<TutorMode>('adaptive');
  const [profileId, setProfileId] = useState('');
  const [experienceMode, setExperienceMode] = useState<'manual' | 'automatic'>('manual');
  const [readAnswers, setReadAnswers] = useState(false);
  const [readHistory, setReadHistory] = useState(false);
  const [message, setMessage] = useState('');
  const [search, setSearch] = useState('');
  const [tab, setTab] = useState<WorkspaceTab>('chat');
  const [memories, setMemories] = useState<TutorMemory[]>([]);
  const [experiences, setExperiences] = useState<TutorExperience[]>([]);
  const [attachmentIds, setAttachmentIds] = useState<string[]>([]);
  const [attachmentNames, setAttachmentNames] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [listening, setListening] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const endRef = useRef<HTMLDivElement>(null);

  const loadList = useCallback(async () => {
    setError(''); setConversations(null); setConversation(null);
    try {
      const [nextProfiles, nextConversations] = await Promise.all([api.modelProfiles('a5.tutor_reply'), api.tutorConversations(courseId)]);
      setProfiles(nextProfiles); setConversations(nextConversations);
      const preferred = nextProfiles.find((item) => item.available) ?? nextProfiles[0];
      setProfileId(preferred?.id ?? '');
      if (nextConversations[0]) setConversation(await api.tutorConversation(courseId, nextConversations[0].id));
    } catch (reason) { setError(reason instanceof ApiError ? reason.message : '无法读取辅导工作区'); }
  }, [courseId]);
  useEffect(() => { void loadList(); }, [loadList]);
  useEffect(() => { endRef.current?.scrollIntoView({ block: 'end' }); }, [conversation?.messages.length, busy]);

  const activeProfile = useMemo(() => profiles.find((item) => item.id === profileId) ?? null, [profileId, profiles]);

  const openConversation = async (id: string) => {
    setBusy(true); setError('');
    try {
      const next = await api.tutorConversation(courseId, id);
      setConversation(next); setMode(next.selected_mode); setProfileId(next.requested_profile_id); setExperienceMode(next.experience_mode); setTab('chat');
    } catch (reason) { setError(reason instanceof ApiError ? reason.message : '无法打开对话'); }
    finally { setBusy(false); }
  };

  const createConversation = async () => {
    if (!profileId) { setError('当前没有可用的模型配置'); return null; }
    const created = await api.createTutorConversation(courseId, { selected_mode: mode, requested_profile_id: profileId, experience_mode: experienceMode });
    setConversation(created);
    setConversations((rows) => rows ? [{ ...created, preview: '', message_count: 0 }, ...rows] : [{ ...created, preview: '', message_count: 0 }]);
    return created;
  };

  const send = async () => {
    const text = message.trim();
    if (!text || busy) return;
    if (!activeProfile?.available) { setError(activeProfile?.unavailable_reason ?? '所选模型当前不可用'); return; }
    setBusy(true); setError(''); setNotice('');
    try {
      const current = conversation ?? await createConversation();
      if (!current) return;
      setMessage('');
      const optimistic: TutorMessage = { id: clientId(), turn_id: null, ordinal: current.messages.length + 1, role: 'user', title: null, body: text, strategy: null, checkpoint: {}, visual: null, citations: [], inline_practice: null, created_at: new Date().toISOString() };
      setConversation({ ...current, messages: [...current.messages, optimistic] });
      const result = await api.sendTutorTurn(courseId, current.id, {
        client_turn_id: clientId(), message: text, selected_mode: mode, requested_profile_id: profileId,
        history_permissions: { read_answer_history: readAnswers, read_conversation_history: readHistory },
        experience_mode: experienceMode, attachment_ids: attachmentIds, concept_ids: conceptId ? [conceptId] : [], conversation_version: current.version,
      });
      const refreshed = await api.tutorConversation(courseId, current.id);
      setConversation(refreshed); setAttachmentIds([]); setAttachmentNames([]);
      setConversations(await api.tutorConversations(courseId));
      if (result.experience_decision.decision === 'generated') setNotice('本轮已生成一条可追溯教学经验。');
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : '辅导回复生成失败');
      if (conversation) setConversation(await api.tutorConversation(courseId, conversation.id).catch(() => conversation));
    } finally { setBusy(false); }
  };

  const removeConversation = async (item: TutorConversationItem) => {
    if (!window.confirm(`删除对话“${item.title}”？相关对话正文将不再显示。`)) return;
    await api.deleteTutorConversation(courseId, item.id);
    const next = await api.tutorConversations(courseId); setConversations(next);
    setConversation(next[0] ? await api.tutorConversation(courseId, next[0].id) : null);
  };

  const renameConversation = async (item: TutorConversationItem) => {
    const title = window.prompt('新的对话名称', item.title)?.trim();
    if (!title || title === item.title) return;
    const next = await api.renameTutorConversation(courseId, item.id, title, item.version);
    setConversations(await api.tutorConversations(courseId)); if (conversation?.id === item.id) setConversation(next);
  };

  const loadWorkspaceTab = async (next: WorkspaceTab) => {
    setTab(next); setError('');
    try {
      if (next === 'memory') setMemories(await api.tutorMemories(courseId));
      if (next === 'experience') setExperiences(await api.tutorExperiences(courseId));
      } catch (reason) { setError(reason instanceof ApiError ? reason.message : '无法读取历史学习记录'); }
  };

  const generateExperience = async () => {
    if (!conversation || !activeProfile?.available) return;
    setBusy(true);
    try {
      await api.generateTutorExperience(courseId, conversation.id, { idempotency_key: clientId(), requested_profile_id: profileId, conversation_version: conversation.version });
      setExperiences(await api.tutorExperiences(courseId)); setTab('experience');
    } catch (reason) { setError(reason instanceof ApiError ? reason.message : '教学经验生成失败'); }
    finally { setBusy(false); }
  };

  const startSpeech = () => {
    const ctor = (window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor }).SpeechRecognition
      ?? (window as unknown as { webkitSpeechRecognition?: RecognitionCtor }).webkitSpeechRecognition;
    if (!ctor) { setNotice('当前浏览器未提供语音识别能力。'); return; }
    const recognition = new ctor(); recognition.lang = 'zh-CN'; recognition.interimResults = false;
    recognition.onresult = (event) => setMessage((value) => `${value}${value ? ' ' : ''}${event.results[0][0].transcript}`);
    recognition.onerror = () => setNotice('语音识别未完成，请检查浏览器麦克风权限。');
    recognition.onend = () => setListening(false); setListening(true); recognition.start();
  };

  const uploadAttachment = async (file: File) => {
    setBusy(true); setError('');
    try {
      const asset = await api.uploadTutorAttachment(courseId, file);
      setAttachmentIds((items) => [...items, asset.id]); setAttachmentNames((items) => [...items, file.name]);
    } catch (reason) { setError(reason instanceof ApiError ? reason.message : '附件上传或安全解析失败'); }
    finally { setBusy(false); }
  };

  if (error && !conversations) return <ErrorState message={error} retry={() => void loadList()} />;
  if (!conversations) return <LoadingState label="正在读取辅导历史与模型状态…" />;

  return <div className="student-tutor-page">
    <aside className="tutor-history">
      <button className="new-conversation" onClick={() => { setConversation(null); setMessage(''); setTab('chat'); }}><MessageSquarePlus size={17} />新对话</button>
      <label><Search size={15} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索历史对话" /></label>
      <div>{conversations.filter((item) => !search || `${item.title}${item.preview}`.includes(search)).map((item) => <button key={item.id} className={conversation?.id === item.id ? 'active' : ''} onClick={() => void openConversation(item.id)}><span><b>{item.title}</b><small>{item.preview || `${item.message_count} 条消息`}</small></span><em><i title="重命名" onClick={(event) => { event.stopPropagation(); void renameConversation(item); }}><Pencil size={13} /></i><i title="删除" onClick={(event) => { event.stopPropagation(); void removeConversation(item); }}><Trash2 size={13} /></i></em></button>)}</div>
    </aside>

    <section className="tutor-workspace">
      <header className="tutor-workspace-header"><div><span><BrainCircuit size={17} />智伴辅导</span><b>{conversation?.title ?? '新对话'}</b></div><nav><button className={tab === 'chat' ? 'active' : ''} onClick={() => void loadWorkspaceTab('chat')}><Volume2 size={15} />对话</button><button className={tab === 'memory' ? 'active' : ''} onClick={() => void loadWorkspaceTab('memory')}><MemoryStick size={15} />学习记忆</button><button className={tab === 'experience' ? 'active' : ''} onClick={() => void loadWorkspaceTab('experience')}><Lightbulb size={15} />教学经验</button></nav></header>

      {tab === 'chat' && <>
        <div className="tutor-strategy-bar">{modes.map((item) => <button key={item.id} className={mode === item.id ? 'active' : ''} title={item.note} onClick={() => setMode(item.id)}>{item.label}</button>)}</div>
        <div className="tutor-chat-stream">
          {!conversation?.messages.length && <div className="tutor-empty"><Sparkles size={32} /><h2>从当前课程问题开始</h2><p>选择辅导策略后输入问题。模型不可用时会明确显示原因，不会生成固定回复。</p></div>}
          {conversation?.messages.map((item) => <ChatMessage key={item.id} message={item} />)}
          {busy && <div className="tutor-thinking"><LoaderCircle className="spin" size={17} />正在执行策略与质量校验…</div>}<div ref={endRef} />
        </div>
        <div className="tutor-composer">
          <div className="tutor-permissions"><label><input type="checkbox" checked={readAnswers} onChange={(event) => setReadAnswers(event.target.checked)} />授权读取历史作答</label><label><input type="checkbox" checked={readHistory} onChange={(event) => setReadHistory(event.target.checked)} />授权读取历史对话</label><label>经验<select value={experienceMode} onChange={(event) => setExperienceMode(event.target.value as 'manual' | 'automatic')}><option value="manual">手动生成</option><option value="automatic">自动判断</option></select></label></div>
          {attachmentNames.length > 0 && <div className="attachment-chips">{attachmentNames.map((name, index) => <span key={`${name}-${index}`}><FilePlus2 size={13} />{name}<button aria-label={`移除${name}`} onClick={() => { setAttachmentNames((items) => items.filter((_, itemIndex) => itemIndex !== index)); setAttachmentIds((items) => items.filter((_, itemIndex) => itemIndex !== index)); }}><X size={12} /></button></span>)}</div>}
          <textarea value={message} onChange={(event) => setMessage(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void send(); } }} placeholder="输入你正在思考的问题…" />
          <footer><div><label className="icon-button" title="添加课程附件"><FilePlus2 size={17} /><input type="file" accept=".pdf,.docx,.pptx,.txt" hidden onChange={(event) => { const file = event.target.files?.[0]; if (file) void uploadAttachment(file); event.target.value = ''; }} /></label><button className={`icon-button${listening ? ' active' : ''}`} title="语音转文字" onClick={startSpeech}><Mic size={17} /></button><select value={profileId} onChange={(event) => setProfileId(event.target.value)}>{profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.display_name}{profile.available ? '' : '（不可用）'}</option>)}</select></div><button className="send-button" disabled={!message.trim() || busy || !activeProfile?.available} title={!activeProfile?.available ? activeProfile?.unavailable_reason ?? '模型不可用' : '发送'} onClick={() => void send()}><Send size={17} /></button></footer>
          {activeProfile && !activeProfile.available && <p className="model-unavailable">{activeProfile.display_name}：{activeProfile.unavailable_reason}</p>}
        </div>
      </>}

      {tab === 'memory' && <div className="tutor-library"><header><div><span>来源可追溯</span><h2>长期学习记忆</h2></div><button disabled={busy} onClick={() => { setBusy(true); void api.compressTutorMemories(courseId).then(setMemories).catch((reason) => setError(reason instanceof ApiError ? reason.message : '记忆压缩失败')).finally(() => setBusy(false)); }}>整理记忆</button></header>{memories.length ? memories.map((memory) => <article key={memory.id}><div><span>{memory.memory_kind}</span><em>置信度 {Math.round(memory.confidence * 100)}%</em></div><p>{memory.content}</p><footer><small>{memory.source_count} 条有效来源</small><button onClick={() => void api.resolveTutorMemory(courseId, memory.id, { action: 'confirm', replacement_content: null }).then(() => loadWorkspaceTab('memory'))}><Check size={14} />确认</button><button onClick={() => void api.resolveTutorMemory(courseId, memory.id, { action: 'delete', replacement_content: null }).then(() => loadWorkspaceTab('memory'))}><Trash2 size={14} />删除</button><button onClick={() => { const replacement = window.prompt('新的记忆内容', memory.content)?.trim(); if (replacement) void api.resolveTutorMemory(courseId, memory.id, { action: 'supersede', replacement_content: replacement }).then(() => loadWorkspaceTab('memory')); }}>替换</button></footer></article>) : <div className="empty-result"><MemoryStick size={28} /><p>尚无通过证据约束的学习记忆。</p></div>}</div>}

      {tab === 'experience' && <div className="tutor-library"><header><div><span>仅学生本人可见</span><h2>教学经验</h2></div><button disabled={!conversation || busy || !activeProfile?.available} onClick={() => void generateExperience()}><Plus size={15} />从当前对话生成</button></header>{experiences.length ? experiences.map((experience) => <article key={experience.id}><div><span>{experience.generation_mode}</span><em>置信度 {Math.round(experience.confidence * 100)}%</em></div><h3>{experience.title}</h3><p>{experience.method}</p><footer><small>{experience.evidence_summary}</small><button onClick={() => void api.deleteTutorExperience(courseId, experience.id).then(() => loadWorkspaceTab('experience'))}><Trash2 size={14} />删除</button></footer></article>) : <div className="empty-result"><Lightbulb size={28} /><p>尚无满足证据门的教学经验。</p></div>}</div>}
      {notice && <div className="success-notice">{notice}</div>}{error && <div className="inline-error">{error}</div>}
    </section>
  </div>;
}
