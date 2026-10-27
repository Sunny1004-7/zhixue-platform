import {
  BrainCircuit,
  Check,
  ChevronRight,
  FilePlus2,
  History,
  Lightbulb,
  LoaderCircle,
  MemoryStick,
  MessageSquarePlus,
  Mic,
  Network,
  Pencil,
  Plus,
  Search,
  Send,
  Sparkles,
  Trash2,
  Volume2,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useDialogs } from "../components/Dialogs";
import { useAuth } from "../AuthContext";
import { ApiError } from "../errors";
import { useApi } from "../RuntimeContext";
import { ErrorState, LoadingState } from "../components/Primitives";
import { useCourse } from "../CourseContext";
import type {
  ModelProfile,
  TutorConversation,
  TutorConversationItem,
  TutorExperience,
  TutorMemory,
  TutorMessage,
  TutorMode,
} from "../types";

const modes: Array<{ id: TutorMode; label: string; note: string }> = [
  { id: "adaptive", label: "自适应选择", note: "依据问题与学习状态路由" },
  { id: "coach", label: "启发引导", note: "通过追问形成推理链" },
  { id: "visualize", label: "可视化解释", note: "输出可访问的结构图示" },
  { id: "practice", label: "即时练习", note: "接入当前课程题组" },
  { id: "research", label: "联网研证", note: "给出可核验来源" },
  { id: "explain", label: "类比拆解", note: "分步解释抽象概念" },
];

type WorkspaceTab = "chat" | "memory" | "experience";
type SpeechResultEvent = { results: ArrayLike<{ 0: { transcript: string } }> };
type Recognition = {
  lang: string;
  interimResults: boolean;
  start: () => void;
  onresult: ((event: SpeechResultEvent) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
};
type RecognitionCtor = new () => Recognition;

function clientId() {
  return `turn:${crypto.randomUUID()}`;
}

function VisualExplanation({ visual }: { visual: Record<string, unknown> }) {
  const nodes = Array.isArray(visual.nodes)
    ? (visual.nodes as Array<{ id?: string; label?: string; detail?: string }>)
    : [];
  const edges = Array.isArray(visual.edges)
    ? (visual.edges as Array<{
        source?: string;
        target?: string;
        label?: string;
      }>)
    : [];
  return (
    <figure
      className="tutor-visual"
      aria-label={String(visual.alt_text ?? visual.title ?? "辅导图示")}
    >
      <figcaption>{String(visual.title ?? "结构图示")}</figcaption>
      <div>
        {nodes.map((node, index) => (
          <div key={node.id ?? index}>
            <span>{index + 1}</span>
            <b>{node.label ?? "节点"}</b>
            {node.detail && <small>{node.detail}</small>}
          </div>
        ))}
      </div>
      {edges.length > 0 && (
        <p>
          {edges
            .map(
              (edge) =>
                `${nodes.find((node) => node.id === edge.source)?.label ?? "知识节点"} → ${nodes.find((node) => node.id === edge.target)?.label ?? "知识节点"}${edge.label ? `（${edge.label}）` : ""}`,
            )
            .join(" · ")}
        </p>
      )}
    </figure>
  );
}

function ChatMessage({ message }: { message: TutorMessage }) {
  const navigate = useNavigate();
  const { courseId } = useCourse();
  return (
    <article className={`tutor-message tutor-message--${message.role}`}>
      <span>
        {message.role === "assistant" ? <Sparkles size={16} /> : "我"}
      </span>
      <div>
        {message.title && <h3>{message.title}</h3>}
        <p>
          {message.body
            .split(/(\*\*[^*]+\*\*)/g)
            .map((part, index) =>
              part.startsWith("**") && part.endsWith("**") ? (
                <strong key={index}>{part.slice(2, -2)}</strong>
              ) : (
                part
              ),
            )}
        </p>
        {message.visual && <VisualExplanation visual={message.visual} />}
        {message.role === "assistant" &&
          typeof message.checkpoint?.criterion === "string" &&
          message.checkpoint.criterion.trim() && (
            <section className="tutor-inline-practice tutor-checkpoint">
              <b>理解检查</b>
              <p>{message.checkpoint.criterion}</p>
            </section>
          )}
        {message.inline_practice && (
          <section className="tutor-inline-practice">
            <b>即时练习</b>
            <p>
              {String(
                message.inline_practice.prompt ??
                  "请进入智适练习完成当前题目。",
              )}
            </p>
            {Array.isArray(message.inline_practice.options) && (
              <div>
                {(
                  message.inline_practice.options as Array<{
                    id?: string;
                    content?: string;
                  }>
                ).map((option, index) => (
                  <span key={option.id ?? index}>
                    {String.fromCharCode(65 + index)}. {option.content ?? ""}
                  </span>
                ))}
              </div>
            )}
            <button
              type="button"
              onClick={() => {
                navigate("/student/practice", {
                  state: {
                    courseId,
                    questionSetId: message.inline_practice?.question_set_id,
                  },
                });
              }}
            >
              进入智适练习
            </button>
          </section>
        )}
        {message.citations.length > 0 && (
          <footer>
            {message.citations.map((citation, index) =>
              citation.url ? (
                <a
                  key={`${citation.url}-${index}`}
                  href={citation.url}
                  target="_blank"
                  rel="noreferrer"
                >
                  <Network size={14} />
                  {citation.label ?? `来源 ${index + 1}`}
                </a>
              ) : null,
            )}
          </footer>
        )}
      </div>
    </article>
  );
}

export default function StudentTutorPage() {
  const api = useApi();
  const { courseId } = useCourse();
  const location = useLocation();
  const dialogs = useDialogs();
  const { user } = useAuth();
  const requestEpoch = useRef(0);
  const sendLock = useRef(false);
  const pendingTurn = useRef<{
    id: string;
    text: string;
    attachments: string[];
    conversationId: string;
    payload?: Record<string, unknown>;
    beforeCount?: number;
  } | null>(null);
  const [uncertain, setUncertain] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const conceptId =
    typeof (location.state as { conceptId?: unknown } | null)?.conceptId ===
    "string"
      ? String((location.state as { conceptId: string }).conceptId)
      : null;
  const [profiles, setProfiles] = useState<ModelProfile[]>([]);
  const [conversations, setConversations] = useState<
    TutorConversationItem[] | null
  >(null);
  const [conversation, setConversation] = useState<TutorConversation | null>(
    null,
  );
  const [mode, setMode] = useState<TutorMode>("adaptive");
  const [profileId, setProfileId] = useState("");
  const [experienceMode, setExperienceMode] = useState<"manual" | "automatic">(
    "manual",
  );
  const [readAnswers, setReadAnswers] = useState(false);
  const [readHistory, setReadHistory] = useState(false);
  const draftKey = "zhixue-draft:tutor:" + user!.id + ":" + courseId;
  const savedDraft = () => {
    try {
      return JSON.parse(sessionStorage.getItem(draftKey) || "{}");
    } catch {
      return {};
    }
  };
  const [message, setMessage] = useState<string>(
    () => savedDraft().message || "",
  );
  const [search, setSearch] = useState("");
  const [tab, setTab] = useState<WorkspaceTab>("chat");
  const [memories, setMemories] = useState<TutorMemory[]>([]);
  const [experiences, setExperiences] = useState<TutorExperience[]>([]);
  const [attachmentIds, setAttachmentIds] = useState<string[]>(
    () => savedDraft().ids || [],
  );
  const [attachmentNames, setAttachmentNames] = useState<string[]>(
    () => savedDraft().names || [],
  );
  const [busy, setBusy] = useState(false);
  const [listening, setListening] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    sessionStorage.setItem(
      draftKey,
      JSON.stringify({ message, ids: attachmentIds, names: attachmentNames }),
    );
  }, [draftKey, message, attachmentIds, attachmentNames]);
  useEffect(
    () => () => {
      requestEpoch.current++;
    },
    [],
  );

  const loadList = useCallback(async () => {
    const epoch = ++requestEpoch.current;
    setError("");
    setConversations(null);
    setConversation(null);
    try {
      const [nextProfiles, nextConversations] = await Promise.all([
        api.modelProfiles("a5.tutor_reply"),
        api.tutorConversations(courseId),
      ]);
      if (epoch !== requestEpoch.current) return;
      setProfiles(nextProfiles);
      setConversations(nextConversations);
      const preferred =
        nextProfiles.find((item) => item.available) ?? nextProfiles[0];
      setProfileId(preferred?.id ?? "");
      if (nextConversations[0]) {
        const detail = await api.tutorConversation(
          courseId,
          nextConversations[0].id,
        );
        if (epoch === requestEpoch.current) setConversation(detail);
      }
    } catch (reason) {
      setError(
        reason instanceof ApiError ? reason.message : "无法读取辅导工作区",
      );
    }
  }, [courseId]);
  useEffect(() => {
    void loadList();
  }, [loadList]);
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [conversation?.messages.length, busy]);

  const activeProfile = useMemo(
    () => profiles.find((item) => item.id === profileId) ?? null,
    [profileId, profiles],
  );

  const openConversation = async (id: string) => {
    if (busy) return;
    const epoch = ++requestEpoch.current;
    setBusy(true);
    setError("");
    try {
      const next = await api.tutorConversation(courseId, id);
      if (epoch !== requestEpoch.current) return;
      setHistoryOpen(false);
      setConversation(next);
      setMode(next.selected_mode);
      setProfileId(next.requested_profile_id);
      setExperienceMode(next.experience_mode);
      setTab("chat");
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "无法打开对话");
    } finally {
      setBusy(false);
    }
  };

  const createConversation = async () => {
    if (!profileId) {
      setError("当前没有可用的模型配置");
      return null;
    }
    const created = await api.createTutorConversation(courseId, {
      selected_mode: mode,
      requested_profile_id: profileId,
      experience_mode: experienceMode,
    });
    setConversation(created);
    setConversations((rows) =>
      rows
        ? [{ ...created, preview: "", message_count: 0 }, ...rows]
        : [{ ...created, preview: "", message_count: 0 }],
    );
    return created;
  };

  const send = async () => {
    const text = message.trim();
    if (!text || sendLock.current || busy || uncertain) return;
    if (!activeProfile?.available) {
      setError("当前辅导服务不可用，请稍后重试或联系课程教师。");
      return;
    }
    sendLock.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    let current = conversation;
    try {
      current = current ?? (await createConversation());
      if (!current) return;
      const previous = pendingTurn.current;
      const submission: NonNullable<typeof pendingTurn.current> =
        previous &&
        previous.text === text &&
        previous.conversationId === current.id &&
        JSON.stringify(previous.attachments) === JSON.stringify(attachmentIds)
          ? previous
          : {
              id: clientId(),
              text,
              attachments: [...attachmentIds],
              conversationId: current.id,
            };
      pendingTurn.current = submission;
      submission.payload ??= {
        client_turn_id: submission.id,
        message: text,
        selected_mode: mode,
        requested_profile_id: profileId,
        history_permissions: {
          read_answer_history: readAnswers,
          read_conversation_history: readHistory,
        },
        experience_mode: experienceMode,
        attachment_ids: submission.attachments,
        concept_ids: conceptId ? [conceptId] : [],
        conversation_version: current.version,
      };
      submission.beforeCount ??= current.messages.length;
      const result = await api.sendTutorTurn(
        courseId,
        current.id,
        submission.payload,
      );
      const refreshed = await api.tutorConversation(courseId, current.id);
      setConversation(refreshed);
      setMessage("");
      setAttachmentIds([]);
      setAttachmentNames([]);
      pendingTurn.current = null;
      setConversations(await api.tutorConversations(courseId));
      if (result.experience_decision.decision === "generated")
        setNotice("已生成一条教学经验，可在教学经验中查看。");
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : "连接中断，暂时无法确认本次提问是否处理完成。请先核对对话记录。",
      );
      if (!(reason instanceof ApiError) || reason.status === 409) {
        setUncertain(true);
      } else {
        pendingTurn.current = null;
      }
      if (current)
        try {
          setConversation(await api.tutorConversation(courseId, current.id));
        } catch {
          /* Keep the draft and avoid automatic resubmission. */
        }
    } finally {
      sendLock.current = false;
      setBusy(false);
    }
  };
  const reconcile = async () => {
    if (!conversation || busy) return;
    setBusy(true);
    try {
      const next = await api.tutorConversation(courseId, conversation.id);
      setConversation(next);
      setUncertain(false);
      const pending = pendingTurn.current;
      const tail = next.messages.slice(
        pending?.beforeCount ?? next.messages.length,
      );
      if (
        pending &&
        tail.some((x) => x.role === "user" && x.body === pending.text) &&
        tail.some((x) => x.role === "assistant")
      ) {
        setMessage("");
        setAttachmentIds([]);
        setAttachmentNames([]);
        pendingTurn.current = null;
        setNotice("已找到本次提问与回复，输入已清空。");
      } else {
        setNotice(
          "已重新读取对话记录。核对后可再次发送；系统沿用本次请求标识核对处理结果。",
        );
      }
    } catch {
      setError("仍无法核对对话，请恢复网络后重试。");
    } finally {
      setBusy(false);
    }
  };
  const removeConversation = async (item: TutorConversationItem) => {
    if (
      busy ||
      !(await dialogs.confirm(
        "删除对话",
        "删除“" + item.title + "”后，相关对话正文将不再显示。",
        true,
      ))
    )
      return;
    setBusy(true);
    setError("");
    try {
      await api.deleteTutorConversation(courseId, item.id);
      const rows = await api.tutorConversations(courseId);
      setConversations(rows);
      if (conversation?.id === item.id)
        setConversation(
          rows[0] ? await api.tutorConversation(courseId, rows[0].id) : null,
        );
    } catch (reason) {
      setError(
        reason instanceof ApiError ? reason.message : "删除失败，请重试。",
      );
    } finally {
      setBusy(false);
    }
  };
  const renameConversation = async (item: TutorConversationItem) => {
    const title = (
      await dialogs.prompt(
        "重命名对话",
        item.title,
        "为这段学习讨论取一个便于查找的名称。",
      )
    )?.trim();
    if (!title || title === item.title || busy) return;
    setBusy(true);
    setError("");
    try {
      const next = await api.renameTutorConversation(
        courseId,
        item.id,
        title,
        item.version,
      );
      setConversations(await api.tutorConversations(courseId));
      if (conversation?.id === item.id) setConversation(next);
    } catch (reason) {
      setError(
        reason instanceof ApiError ? reason.message : "重命名失败，请重试。",
      );
    } finally {
      setBusy(false);
    }
  };
  const resolveMemory = async (
    memory: TutorMemory,
    action: "confirm" | "delete" | "supersede",
  ) => {
    let replacement: string | null = null;
    if (
      action === "delete" &&
      !(await dialogs.confirm(
        "删除学习记忆",
        "删除后，这条内容将不再用于后续辅导。",
        true,
      ))
    )
      return;
    if (action === "supersede") {
      replacement = await dialogs.prompt(
        "替换学习记忆",
        memory.content,
        "请确认新的记忆内容。",
      );
      if (!replacement) return;
    }
    setBusy(true);
    setError("");
    try {
      await api.resolveTutorMemory(courseId, memory.id, {
        action,
        replacement_content: replacement,
      });
      setMemories(await api.tutorMemories(courseId));
    } catch (reason) {
      setError(
        reason instanceof ApiError ? reason.message : "学习记忆保存失败。",
      );
    } finally {
      setBusy(false);
    }
  };
  const removeExperience = async (id: string) => {
    if (
      !(await dialogs.confirm(
        "删除教学经验",
        "删除后将不再使用这条经验。",
        true,
      ))
    )
      return;
    setBusy(true);
    try {
      await api.deleteTutorExperience(courseId, id);
      setExperiences(await api.tutorExperiences(courseId));
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "删除失败。");
    } finally {
      setBusy(false);
    }
  };

  const loadWorkspaceTab = async (next: WorkspaceTab) => {
    setTab(next);
    setError("");
    try {
      if (next === "memory") setMemories(await api.tutorMemories(courseId));
      if (next === "experience")
        setExperiences(await api.tutorExperiences(courseId));
    } catch (reason) {
      setError(
        reason instanceof ApiError ? reason.message : "无法读取历史学习记录",
      );
    }
  };

  const generateExperience = async () => {
    if (!conversation || !activeProfile?.available) return;
    setBusy(true);
    try {
      await api.generateTutorExperience(courseId, conversation.id, {
        idempotency_key: clientId(),
        requested_profile_id: profileId,
        conversation_version: conversation.version,
      });
      setExperiences(await api.tutorExperiences(courseId));
      setTab("experience");
    } catch (reason) {
      setError(
        reason instanceof ApiError ? reason.message : "教学经验生成失败",
      );
    } finally {
      setBusy(false);
    }
  };

  const startSpeech = () => {
    const ctor =
      (
        window as unknown as {
          SpeechRecognition?: RecognitionCtor;
          webkitSpeechRecognition?: RecognitionCtor;
        }
      ).SpeechRecognition ??
      (window as unknown as { webkitSpeechRecognition?: RecognitionCtor })
        .webkitSpeechRecognition;
    if (!ctor) {
      setNotice("当前浏览器未提供语音识别能力。");
      return;
    }
    const recognition = new ctor();
    recognition.lang = "zh-CN";
    recognition.interimResults = false;
    recognition.onresult = (event) =>
      setMessage(
        (value) =>
          `${value}${value ? " " : ""}${event.results[0][0].transcript}`,
      );
    recognition.onerror = () =>
      setNotice("语音识别未完成，请检查浏览器麦克风权限。");
    recognition.onend = () => setListening(false);
    setListening(true);
    recognition.start();
  };

  const uploadAttachment = async (file: File) => {
    setBusy(true);
    setError("");
    try {
      const asset = await api.uploadTutorAttachment(courseId, file);
      setAttachmentIds((items) => [...items, asset.id]);
      setAttachmentNames((items) => [...items, file.name]);
    } catch (reason) {
      setError(
        reason instanceof ApiError ? reason.message : "附件上传或安全解析失败",
      );
    } finally {
      setBusy(false);
    }
  };

  if (error && !conversations)
    return <ErrorState message={error} retry={() => void loadList()} />;
  if (!conversations)
    return <LoadingState label="正在读取辅导历史与模型状态…" />;

  return (
    <div className="student-tutor-page">
      <aside className={"tutor-history" + (historyOpen ? " is-open" : "")}>
        <button
          className="new-conversation"
          disabled={busy}
          onClick={async () => {
            if (
              (message.trim() || attachmentIds.length) &&
              !(await dialogs.confirm(
                "开始新对话",
                "当前输入将保存在课程草稿中。是否开始新的讨论？",
              ))
            )
              return;
            setConversation(null);
            setTab("chat");
            setHistoryOpen(false);
            pendingTurn.current = null;
            setUncertain(false);
          }}
        >
          <MessageSquarePlus size={17} />
          新对话
        </button>
        <label>
          <Search size={15} />
          <input
            aria-label="搜索历史对话"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索历史对话"
          />
        </label>
        <div className="conversation-list">
          {conversations
            .filter((x) => !search || (x.title + x.preview).includes(search))
            .map((item) => (
              <div
                key={item.id}
                className={
                  "conversation-row" +
                  (conversation?.id === item.id ? " active" : "")
                }
              >
                <button
                  disabled={busy}
                  className="conversation-open"
                  onClick={() => void openConversation(item.id)}
                >
                  <b>{item.title}</b>
                  <small>
                    {item.preview || item.message_count + " 条消息"}
                  </small>
                </button>
                <div>
                  <button
                    disabled={busy}
                    aria-label={"重命名" + item.title}
                    onClick={() => void renameConversation(item)}
                  >
                    <Pencil size={14} />
                  </button>
                  <button
                    disabled={busy}
                    aria-label={"删除" + item.title}
                    onClick={() => void removeConversation(item)}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            ))}
        </div>
      </aside>

      <section className="tutor-workspace">
        <header className="tutor-workspace-header">
          <button
            className="mobile-only"
            aria-expanded={historyOpen}
            onClick={() => setHistoryOpen(!historyOpen)}
          >
            <History size={17} />
            历史对话
          </button>
          <div>
            <span>
              <BrainCircuit size={17} />
              智伴辅导
            </span>
            <b>{conversation?.title ?? "新对话"}</b>
          </div>
          <nav>
            <button
              className={tab === "chat" ? "active" : ""}
              onClick={() => void loadWorkspaceTab("chat")}
            >
              <Volume2 size={15} />
              对话
            </button>
            <button
              className={tab === "memory" ? "active" : ""}
              onClick={() => void loadWorkspaceTab("memory")}
            >
              <MemoryStick size={15} />
              学习记忆
            </button>
            <button
              className={tab === "experience" ? "active" : ""}
              onClick={() => void loadWorkspaceTab("experience")}
            >
              <Lightbulb size={15} />
              教学经验
            </button>
          </nav>
        </header>

        {tab === "chat" && (
          <>
            <div className="tutor-strategy-bar">
              {modes.map((item) => (
                <button
                  key={item.id}
                  className={mode === item.id ? "active" : ""}
                  title={item.note}
                  onClick={() => setMode(item.id)}
                >
                  {item.label}
                </button>
              ))}
            </div>
            <div className="tutor-chat-stream">
              {!conversation?.messages.length && (
                <div className="tutor-empty">
                  <Sparkles size={32} />
                  <h2>从当前课程问题开始</h2>
                  <p>
                    结合知识点、解题步骤或课程材料提出问题，继续你的学习讨论。
                  </p>
                </div>
              )}
              {conversation?.messages.map((item) => (
                <ChatMessage key={item.id} message={item} />
              ))}
              {busy && (
                <div className="tutor-thinking">
                  <LoaderCircle className="spin" size={17} />
                  正在等待服务返回，请稍候…
                </div>
              )}
              <div ref={endRef} />
            </div>
            <div className="tutor-composer">
              <div className="tutor-permissions">
                <label>
                  <input
                    type="checkbox"
                    checked={readAnswers}
                    onChange={(event) => setReadAnswers(event.target.checked)}
                  />
                  授权读取历史作答
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={readHistory}
                    onChange={(event) => setReadHistory(event.target.checked)}
                  />
                  授权读取历史对话
                </label>
                <label>
                  经验
                  <select
                    value={experienceMode}
                    onChange={(event) =>
                      setExperienceMode(
                        event.target.value as "manual" | "automatic",
                      )
                    }
                  >
                    <option value="manual">手动生成</option>
                    <option value="automatic">自动判断</option>
                  </select>
                </label>
              </div>
              {attachmentNames.length > 0 && (
                <div className="attachment-chips">
                  {attachmentNames.map((name, index) => (
                    <span key={`${name}-${index}`}>
                      <FilePlus2 size={13} />
                      {name}
                      <button
                        aria-label={`移除${name}`}
                        onClick={() => {
                          setAttachmentNames((items) =>
                            items.filter((_, itemIndex) => itemIndex !== index),
                          );
                          setAttachmentIds((items) =>
                            items.filter((_, itemIndex) => itemIndex !== index),
                          );
                        }}
                      >
                        <X size={12} />
                      </button>
                    </span>
                  ))}
                </div>
              )}
              <label className="sr-only" htmlFor="tutor-message">
                向智伴提问
              </label>
              <textarea
                id="tutor-message"
                disabled={busy || uncertain}
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                onKeyDown={(event) => {
                  if (
                    event.key === "Enter" &&
                    !event.shiftKey &&
                    !event.nativeEvent.isComposing &&
                    event.keyCode !== 229
                  ) {
                    event.preventDefault();
                    void send();
                  }
                }}
                placeholder="输入你正在思考的问题…"
              />
              <footer>
                <div>
                  <label
                    className="icon-button"
                    title="添加课程附件"
                    tabIndex={0}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        e.currentTarget.querySelector("input")?.click();
                      }
                    }}
                  >
                    <span className="sr-only">添加课程附件</span>
                    <FilePlus2 size={17} />
                    <input
                      type="file"
                      disabled={busy}
                      aria-label="课程附件"
                      accept=".pdf,.docx,.pptx,.txt"
                      hidden
                      onChange={(event) => {
                        const file = event.target.files?.[0];
                        if (file) void uploadAttachment(file);
                        event.target.value = "";
                      }}
                    />
                  </label>
                  <button
                    className={`icon-button${listening ? " active" : ""}`}
                    aria-label="语音转文字"
                    title="语音转文字"
                    onClick={startSpeech}
                  >
                    <Mic size={17} />
                  </button>
                  <select
                    aria-label="辅导模型"
                    disabled={busy}
                    value={profileId}
                    onChange={(event) => setProfileId(event.target.value)}
                  >
                    {profiles.map((profile) => (
                      <option key={profile.id} value={profile.id}>
                        {profile.display_name}
                        {profile.available ? "" : "（不可用）"}
                      </option>
                    ))}
                  </select>
                </div>
                <button
                  className="send-button"
                  aria-label="发送问题"
                  disabled={
                    !message.trim() ||
                    busy ||
                    uncertain ||
                    !activeProfile?.available
                  }
                  title={
                    !activeProfile?.available
                      ? (activeProfile?.unavailable_reason ?? "模型不可用")
                      : "发送"
                  }
                  onClick={() => void send()}
                >
                  <Send size={17} />
                </button>
              </footer>
              {!activeProfile?.available && (
                <p className="model-unavailable">
                  当前辅导服务暂不可用，输入内容已保留。请稍后重试或联系课程教师。
                </p>
              )}
            </div>
          </>
        )}

        {tab === "memory" && (
          <div className="tutor-library">
            <header>
              <div>
                <span>来源可追溯</span>
                <h2>长期学习记忆</h2>
              </div>
              <button
                disabled={busy}
                onClick={() => {
                  setBusy(true);
                  void api
                    .compressTutorMemories(courseId)
                    .then(setMemories)
                    .catch((reason) =>
                      setError(
                        reason instanceof ApiError
                          ? reason.message
                          : "记忆压缩失败",
                      ),
                    )
                    .finally(() => setBusy(false));
                }}
              >
                整理记忆
              </button>
            </header>
            {memories.length ? (
              memories.map((memory) => (
                <article key={memory.id}>
                  <div>
                    <span>
                      {{
                        explanation_preference: "学习偏好",
                        learning_goal: "学习目标",
                        knowledge_gap: "知识理解",
                        misconception: "概念理解",
                        study_strategy: "学习方法",
                      }[memory.memory_kind] ?? "学习记忆"}
                    </span>
                    <em>置信度 {Math.round(memory.confidence * 100)}%</em>
                  </div>
                  <p>{memory.content}</p>
                  <footer>
                    <small>{memory.source_count} 条有效来源</small>
                    <button
                      disabled={busy}
                      onClick={() => void resolveMemory(memory, "confirm")}
                    >
                      <Check size={14} />
                      确认
                    </button>
                    <button
                      disabled={busy}
                      onClick={() => void resolveMemory(memory, "delete")}
                    >
                      <Trash2 size={14} />
                      删除
                    </button>
                    <button
                      disabled={busy}
                      onClick={() => void resolveMemory(memory, "supersede")}
                    >
                      替换
                    </button>
                  </footer>
                </article>
              ))
            ) : (
              <div className="empty-result">
                <MemoryStick size={28} />
                <p>尚无通过证据约束的学习记忆。</p>
              </div>
            )}
          </div>
        )}

        {tab === "experience" && (
          <div className="tutor-library">
            <header>
              <div>
                <span>仅学生本人可见</span>
                <h2>教学经验</h2>
              </div>
              <button
                disabled={!conversation || busy || !activeProfile?.available}
                onClick={() => void generateExperience()}
              >
                <Plus size={15} />
                从当前对话生成
              </button>
            </header>
            {experiences.length ? (
              experiences.map((experience) => (
                <article key={experience.id}>
                  <div>
                    <span>
                      {experience.generation_mode === "automatic"
                        ? "自动整理"
                        : "手动整理"}
                    </span>
                    <em>置信度 {Math.round(experience.confidence * 100)}%</em>
                  </div>
                  <h3>{experience.title}</h3>
                  <p>{experience.method}</p>
                  <footer>
                    <small>{experience.evidence_summary}</small>
                    <button
                      disabled={busy}
                      onClick={() => void removeExperience(experience.id)}
                    >
                      <Trash2 size={14} />
                      删除
                    </button>
                  </footer>
                </article>
              ))
            ) : (
              <div className="empty-result">
                <Lightbulb size={28} />
                <p>积累有效讨论后，可从对话中整理教学经验。</p>
              </div>
            )}
          </div>
        )}
        {notice && <div className="success-notice">{notice}</div>}
        {error && (
          <div className="inline-error" role="alert">
            {error}
            {uncertain && (
              <button disabled={busy} onClick={() => void reconcile()}>
                核对对话记录
              </button>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
