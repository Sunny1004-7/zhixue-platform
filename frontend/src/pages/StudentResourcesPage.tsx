import {
  ArrowRight,
  BookOpenCheck,
  Check,
  CirclePlay,
  Expand,
  ExternalLink,
  FileQuestion,
  GitBranch,
  MessageSquareText,
  Play,
  Sparkles,
  Target,
  Video,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { ApiError } from "../errors";
import { useApi } from "../RuntimeContext";
import KnowledgeGraphView from "../components/KnowledgeGraphView";
import { ErrorState, LoadingState, Surface } from "../components/Primitives";
import { useCourse } from "../CourseContext";
import type {
  GraphListItem,
  GraphNode,
  KnowledgeGraph,
  ResourceInboxItem,
  VideoPublication,
} from "../types";

type ResourceTab = "graphs" | "videos" | "inbox";
type CardReading = {
  node: GraphNode;
  graphId: string;
  startedAt: number;
  visibleStartedAt: number | null;
  visibleMs: number;
};

function resourceText(
  resource: Record<string, unknown>,
  key: string,
  fallback: string,
) {
  return typeof resource[key] === "string" && resource[key]
    ? String(resource[key])
    : fallback;
}

function requestKey(scope: string) {
  return `${scope}:${crypto.randomUUID()}`;
}

export default function StudentResourcesPage() {
  const api = useApi();
  const { courseId } = useCourse();
  const navigate = useNavigate();
  const location = useLocation();
  const target = (location.state ?? {}) as {
    resourceId?: string;
    resourceTitle?: string;
    tab?: ResourceTab;
    conceptId?: string;
  };
  const graphRequest = useRef(0);
  const [resourceBusy, setResourceBusy] = useState(false);
  const [items, setItems] = useState<GraphListItem[] | null>(null);
  const [videos, setVideos] = useState<VideoPublication[]>([]);
  const [inbox, setInbox] = useState<ResourceInboxItem[]>([]);
  const [tab, setTab] = useState<ResourceTab>(target.tab ?? "graphs");
  const [graph, setGraph] = useState<KnowledgeGraph | null>(null);
  const [node, setNode] = useState<GraphNode | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [video, setVideo] = useState<VideoPublication | null>(null);
  const [inboxVideo, setInboxVideo] = useState<ResourceInboxItem | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const cardReading = useRef<CardReading | null>(null);

  const finishCardReading = useCallback(async () => {
    const reading = cardReading.current;
    if (!reading) return;
    cardReading.current = null;
    const now = Date.now();
    const visibleMs =
      reading.visibleMs +
      (reading.visibleStartedAt == null ? 0 : now - reading.visibleStartedAt);
    const dwellSeconds = Math.max(0, (now - reading.startedAt) / 1000);
    if (dwellSeconds < 15) return;
    try {
      await api.recordLearningEvent(courseId, {
        idempotency_key: requestKey("knowledge-card"),
        event_type: "knowledge_card_opened",
        object_type: "knowledge_graph_node",
        object_id: reading.node.id,
        concepts: [{ concept_id: reading.node.concept_id, weight: 1 }],
        completion: Math.min(1, dwellSeconds / 120),
        upstream_confidence: reading.node.confidence,
        alignment_confidence: reading.node.confidence,
        occurred_at: new Date(now).toISOString(),
        payload: {
          graph_id: reading.graphId,
          dwell_seconds: Math.round(dwellSeconds * 10) / 10,
          foreground_ratio: Math.max(
            0,
            Math.min(1, visibleMs / Math.max(1, now - reading.startedAt)),
          ),
        },
      });
    } catch (reason) {
      setError(
        reason instanceof ApiError ? reason.message : "无法记录知识卡学习证据",
      );
    }
  }, [courseId]);

  useEffect(() => {
    const onVisibilityChange = () => {
      const reading = cardReading.current;
      if (!reading) return;
      const now = Date.now();
      if (reading.visibleStartedAt != null) {
        reading.visibleMs += now - reading.visibleStartedAt;
        reading.visibleStartedAt = null;
      }
      if (document.visibilityState === "visible")
        reading.visibleStartedAt = now;
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () =>
      document.removeEventListener("visibilitychange", onVisibilityChange);
  }, []);

  useEffect(
    () => () => {
      void finishCardReading();
    },
    [finishCardReading],
  );

  const load = useCallback(async () => {
    setError("");
    setItems(null);
    setGraph(null);
    setVideo(null);
    setInboxVideo(null);
    try {
      const [graphs, videoRows, inboxRows] = await Promise.all([
        api.studentGraphs(courseId),
        api.studentVideoResources(courseId),
        api.resourceInbox(courseId),
      ]);
      setItems(graphs);
      setVideos(videoRows);
      setInbox(inboxRows);
      const desired = graphs.find(
        (g) => g.id === target.resourceId || g.title === target.resourceTitle,
      );
      if (desired) {
        const detail = await api.studentGraph(courseId, desired.id);
        setGraph(detail);
      } else if (target.conceptId) {
        for (const item of graphs) {
          const detail = await api.studentGraph(courseId, item.id);
          const node = detail.nodes.find(
            (n) => n.concept_id === target.conceptId,
          );
          if (node) {
            setGraph(detail);
            openKnowledgeCard(node);
            break;
          }
        }
      }
      if (target.tab === "videos") {
        const desiredVideo = videoRows.find(
          (v) =>
            v.id === target.resourceId ||
            v.resource.title === target.resourceTitle,
        );
        if (desiredVideo) setVideo(desiredVideo);
        else if (target.resourceTitle)
          setNotice("这项视频目前没有可接收的发布版本，请查看教师最新推荐。");
      }
    } catch (reason) {
      setError(
        reason instanceof ApiError ? reason.message : "无法读取课程资源",
      );
    }
  }, [courseId]);
  useEffect(() => {
    void load();
  }, [load]);

  const personalizedCount = useMemo(
    () => inbox.filter((item) => item.personalized).length,
    [inbox],
  );
  const openGraph = async (id: string) => {
    const epoch = ++graphRequest.current;
    try {
      const next = await api.studentGraph(courseId, id);
      if (epoch !== graphRequest.current) return;
      setGraph(next);
      setNode(null);
    } catch (reason) {
      if (epoch === graphRequest.current)
        setError(
          reason instanceof ApiError ? reason.message : "无法打开知识图谱",
        );
    }
  };
  const openKnowledgeCard = (next: GraphNode) => {
    void finishCardReading();
    setNode(next);
    const now = Date.now();
    cardReading.current = {
      node: next,
      graphId: graph?.id ?? "",
      startedAt: now,
      visibleStartedAt: document.visibilityState === "visible" ? now : null,
      visibleMs: 0,
    };
    void api
      .recordLearningEvent(courseId, {
        idempotency_key: requestKey("graph-node"),
        event_type: "graph_node_viewed",
        object_type: "knowledge_graph_node",
        object_id: next.id,
        concepts: [{ concept_id: next.concept_id, weight: 1 }],
        completion: 0,
        upstream_confidence: next.confidence,
        alignment_confidence: next.confidence,
        occurred_at: new Date(now).toISOString(),
        payload: {
          graph_id: graph?.id,
          dwell_seconds: 0,
          foreground_ratio: document.visibilityState === "visible" ? 1 : 0,
        },
      })
      .catch((reason) =>
        setError(
          reason instanceof ApiError ? reason.message : "无法记录图谱学习行为",
        ),
      );
  };
  const closeKnowledgeCard = () => {
    void finishCardReading();
    setNode(null);
  };
  const closeGraph = () => {
    graphRequest.current++;
    void finishCardReading();
    setNode(null);
    setGraph(null);
  };

  const openVideo = async (publication: VideoPublication) => {
    setError("");
    setNotice("");
    try {
      await api.recordVideoEvent(
        publication.id,
        {
          event_type: "opened",
          occurred_at: new Date().toISOString(),
          player_signal: "page_only",
          position_seconds: null,
          active_seconds_delta: 0,
          foreground_ratio: 0,
          chapter_id: null,
          feedback: null,
        },
        requestKey("video-open"),
      );
      setVideo(publication);
    } catch (reason) {
      setError(
        reason instanceof ApiError ? reason.message : "无法打开视频资源",
      );
    }
  };

  const finishVideo = async (publication: VideoPublication) => {
    try {
      const result = (await api.recordVideoEvent(
        publication.id,
        {
          event_type: "completed",
          occurred_at: new Date().toISOString(),
          player_signal: "page_only",
          position_seconds: 0,
          active_seconds_delta: 0,
          foreground_ratio: 0,
          chapter_id: null,
          feedback: null,
        },
        requestKey("video-complete"),
      )) as { progress?: { evidence_scope?: string; completed?: boolean } };
      setNotice(
        result.progress?.completed
          ? "观看完成状态已由可信播放器证据确认。"
          : "已记录学习交互；当前来源没有可验证播放器信号，因此未计为可信观看完成。",
      );
    } catch (reason) {
      setError(
        reason instanceof ApiError ? reason.message : "无法记录视频学习状态",
      );
    }
  };

  const openInbox = async (item: ResourceInboxItem) => {
    try {
      const next = await api.openInboxResource(
        item.exposure_id,
        requestKey("inbox-open"),
      );
      setInbox((rows) =>
        rows.map((row) => (row.exposure_id === item.exposure_id ? next : row)),
      );
      const resourceId =
        typeof next.resource.resource_id === "string"
          ? next.resource.resource_id
          : null;
      if (next.resource_type === "question_set")
        navigate("/student/practice", {
          state: { courseId, questionSetId: resourceId },
        });
      else if (next.resource_type === "graph" && resourceId) {
        setTab("graphs");
        await openGraph(resourceId);
      } else if (next.resource_type === "video") {
        setTab("inbox");
        setInboxVideo(next);
      } else {
        setTab(next.resource_type === "graph" ? "graphs" : "videos");
      }
    } catch (reason) {
      setError(
        reason instanceof ApiError ? reason.message : "无法打开定向资源",
      );
    }
  };

  const completeInbox = async (item: ResourceInboxItem) => {
    try {
      const next = await api.completeInboxResource(
        item.exposure_id,
        requestKey("inbox-complete"),
      );
      setInbox((rows) =>
        rows.map((row) => (row.exposure_id === item.exposure_id ? next : row)),
      );
      if (inboxVideo?.exposure_id === next.exposure_id) setInboxVideo(next);
      setNotice("资源完成状态已保存。");
    } catch (reason) {
      setError(
        reason instanceof ApiError ? reason.message : "无法记录资源完成状态",
      );
    } finally {
      setResourceBusy(false);
    }
  };

  if (error && !items)
    return <ErrorState message={error} retry={() => void load()} />;
  if (!items) return <LoadingState label="正在读取教师已发布资源…" />;
  return (
    <div className="graph-resource-page">
      <section className="resource-hero">
        <div>
          <span>
            <BookOpenCheck size={15} />
            当前课程资源
          </span>
          <h2>学习资源</h2>
          <p>
            知识图谱、已审核习题、可核验教学视频与教师定向资源统一回流学习轨迹。
          </p>
        </div>
        <div>
          <b>
            {
              new Set([
                ...items.map((x) => "graph:" + x.id),
                ...videos.map((x) => "video:" + x.candidate_id),
                ...inbox.map(
                  (x) => x.resource_type + ":" + x.resource.resource_id,
                ),
              ]).size
            }
          </b>
          <span>项可用资源</span>
        </div>
      </section>
      <Surface className="graph-library">
        <div className="resource-tabs">
          <button
            className={tab === "graphs" ? "active" : ""}
            onClick={() => setTab("graphs")}
          >
            <GitBranch size={16} />
            知识图谱
          </button>
          <button
            className={tab === "videos" ? "active" : ""}
            onClick={() => setTab("videos")}
          >
            <Video size={16} />
            教学视频 {videos.length > 0 && <em>{videos.length}</em>}
          </button>
          <button
            className={tab === "inbox" ? "active" : ""}
            onClick={() => setTab("inbox")}
          >
            <Sparkles size={16} />
            资源收件箱 {personalizedCount > 0 && <em>{personalizedCount}</em>}
          </button>
          <button
            onClick={() =>
              navigate("/student/practice", { state: { courseId } })
            }
          >
            <Target size={16} />
            进入智适练习
          </button>
        </div>

        {tab === "graphs" && (
          <div className="graph-card-grid">
            {!items.length && (
              <div className="empty-result">
                <GitBranch size={28} />
                <h3>教师尚未发布知识图谱</h3>
                <p>可查看其他资源，或等待课程更新。</p>
              </div>
            )}
            {items.map((item) => (
              <article key={item.id}>
                <span>
                  <GitBranch size={22} />
                </span>
                <div>
                  <small>知识图谱 · 已发布</small>
                  <h3>{item.title}</h3>
                  <p>
                    {item.node_count}个知识点 · {item.edge_count}条关系
                  </p>
                </div>
                <button onClick={() => void openGraph(item.id)}>
                  进入图谱 <ArrowRight size={15} />
                </button>
              </article>
            ))}
          </div>
        )}

        {tab === "videos" && (
          <div className="student-video-grid">
            {videos.length ? (
              videos.map((item) => (
                <article key={item.id}>
                  <button
                    className="student-video-cover"
                    aria-label={`播放${resourceText(item.resource, "title", "教学视频")}`}
                    onClick={() => void openVideo(item)}
                  >
                    {typeof item.resource.thumbnail_url === "string" &&
                    item.resource.thumbnail_url ? (
                      <img
                        src={item.resource.thumbnail_url}
                        alt=""
                        referrerPolicy="no-referrer"
                      />
                    ) : (
                      <Video size={36} />
                    )}
                    <span>
                      <Play size={18} />
                    </span>
                  </button>
                  <div>
                    <small>
                      {resourceText(
                        item.resource,
                        "evidence_level",
                        "来源已核验",
                      )}{" "}
                      · {resourceText(item.resource, "content_kind", "video")}
                    </small>
                    <h3>{resourceText(item.resource, "title", "教学视频")}</h3>
                    <p>
                      {resourceText(
                        item.resource,
                        "creator",
                        "作者信息以来源页为准",
                      )}
                    </p>
                    <footer>
                      <button onClick={() => void openVideo(item)}>
                        <CirclePlay size={15} />
                        打开学习
                      </button>
                      <a
                        href={resourceText(item.resource, "canonical_url", "#")}
                        target="_blank"
                        rel="noreferrer"
                      >
                        <ExternalLink size={14} />
                        来源页
                      </a>
                    </footer>
                  </div>
                </article>
              ))
            ) : (
              <div className="empty-result">
                <Video size={28} />
                <p>当前课程尚无已审核发布的视频。</p>
              </div>
            )}
          </div>
        )}

        {tab === "inbox" && (
          <div className="resource-inbox-list">
            {inbox.length ? (
              inbox.map((item) => (
                <article key={item.exposure_id}>
                  <span
                    className={`resource-type-icon resource-type-${item.resource_type}`}
                  >
                    {item.resource_type === "graph" ? (
                      <GitBranch size={19} />
                    ) : item.resource_type === "question_set" ? (
                      <FileQuestion size={19} />
                    ) : (
                      <Video size={19} />
                    )}
                  </span>
                  <div>
                    <small>
                      {item.personalized ? "为我定制" : "教师通用资源"} ·{" "}
                      {new Date(item.delivered_at).toLocaleDateString("zh-CN")}
                    </small>
                    <h3>
                      {resourceText(item.resource, "title", "课程学习资源")}
                    </h3>
                    <p>
                      {resourceText(
                        item.resource,
                        "reason",
                        resourceText(
                          item.resource,
                          "description",
                          "根据当前课程学习状态发布",
                        ),
                      )}
                    </p>
                  </div>
                  <span
                    className={`delivery-status status-${item.delivery_status}`}
                  >
                    {item.completed_at
                      ? "已完成"
                      : item.opened_at
                        ? "已打开"
                        : "未打开"}
                  </span>
                  <footer>
                    <button onClick={() => void openInbox(item)}>
                      打开 <ArrowRight size={14} />
                    </button>
                    {!item.completed_at && (
                      <button
                        disabled={resourceBusy}
                        onClick={() => void completeInbox(item)}
                      >
                        <Check size={14} />
                        标记完成
                      </button>
                    )}
                  </footer>
                </article>
              ))
            ) : (
              <div className="empty-result">
                <Sparkles size={28} />
                <p>当前没有新的定向资源。</p>
              </div>
            )}
          </div>
        )}
      </Surface>
      {notice && <div className="success-notice">{notice}</div>}
      {error && <div className="inline-error">{error}</div>}

      {graph && (
        <div className="dialog-backdrop" onMouseDown={closeGraph}>
          <section
            className={`graph-resource-dialog${expanded ? " expanded" : ""}`}
            role="dialog"
            aria-modal="true"
            aria-label={graph.title}
            onMouseDown={(event) => event.stopPropagation()}
          >
            <header>
              <div>
                <span>知学智教 · 课程知识图谱</span>
                <h3>{graph.title}</h3>
                <p>
                  {graph.nodes.length}个知识点 · {graph.edges.length}条关系
                </p>
              </div>
              <div>
                <button onClick={() => setExpanded((value) => !value)}>
                  <Expand size={16} />
                  {expanded ? "退出全屏" : "全屏查看"}
                </button>
                <button aria-label="关闭" onClick={closeGraph}>
                  <X size={18} />
                </button>
              </div>
            </header>
            <div className="graph-dialog-body">
              <KnowledgeGraphView
                graph={graph}
                onNodeClick={openKnowledgeCard}
              />
              {node && (
                <aside className="knowledge-card">
                  <button
                    aria-label="关闭知识卡片"
                    onClick={closeKnowledgeCard}
                  >
                    <X size={15} />
                  </button>
                  <small>
                    {node.node_type === "foundation"
                      ? "基础知识点"
                      : node.node_type === "core"
                        ? "核心知识点"
                        : "应用知识点"}
                  </small>
                  <h3>{node.label}</h3>
                  {node.mastery != null && (
                    <em>当前掌握度 {Math.round(node.mastery)}%</em>
                  )}
                  <p>{node.definition}</p>
                  <div>
                    <b>学习要点</b>
                    <span>{node.key_point}</span>
                  </div>
                  <div>
                    <b>常见误区</b>
                    <span>{node.misconception}</span>
                  </div>
                  <div>
                    <b>知识关系</b>
                    <span>
                      {graph.edges
                        .filter(
                          (edge) =>
                            edge.from_node_id === node.id ||
                            edge.to_node_id === node.id,
                        )
                        .slice(0, 4)
                        .map((edge) => {
                          const otherId =
                            edge.from_node_id === node.id
                              ? edge.to_node_id
                              : edge.from_node_id;
                          const other = graph.nodes.find(
                            (item) => item.id === otherId,
                          );
                          const label = {
                            prerequisite: "先修",
                            contains: "包含",
                            application: "应用",
                            contrast: "对比",
                          }[edge.relation];
                          return `${label} · ${other?.label ?? "关联知识点"}`;
                        })
                        .join("；") || "暂无已发布关系"}
                    </span>
                  </div>
                  <footer>
                    <button
                      onClick={() => {
                        void finishCardReading();
                        navigate("/student/practice", {
                          state: { conceptId: node.concept_id },
                        });
                      }}
                    >
                      <Target size={15} />
                      进入智适练习
                    </button>
                    <button
                      onClick={() => {
                        void finishCardReading();
                        navigate("/student/tutor", {
                          state: { conceptId: node.concept_id },
                        });
                      }}
                    >
                      <MessageSquareText size={15} />
                      进入智伴辅导
                    </button>
                  </footer>
                </aside>
              )}
            </div>
          </section>
        </div>
      )}

      {video && (
        <div className="dialog-backdrop" onMouseDown={() => setVideo(null)}>
          <section
            className="student-video-dialog"
            role="dialog"
            aria-modal="true"
            aria-label={resourceText(video.resource, "title", "教学视频")}
            onMouseDown={(event) => event.stopPropagation()}
          >
            <header>
              <div>
                <small>
                  {resourceText(video.resource, "evidence_level", "来源已核验")}
                </small>
                <h3>{resourceText(video.resource, "title", "教学视频")}</h3>
              </div>
              <button aria-label="关闭视频" onClick={() => setVideo(null)}>
                <X size={18} />
              </button>
            </header>
            <div>
              {typeof video.resource.embed_url === "string" &&
              video.resource.embed_url ? (
                <iframe
                  src={video.resource.embed_url}
                  title={resourceText(video.resource, "title", "教学视频")}
                  allow="fullscreen; picture-in-picture"
                />
              ) : (
                <div className="video-preview-fallback">
                  <Video size={42} />
                  <p>该来源未提供可嵌入播放器。</p>
                  <a
                    href={resourceText(video.resource, "canonical_url", "#")}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <ExternalLink size={16} />
                    打开来源页
                  </a>
                </div>
              )}
            </div>
            <footer>
              <span>只有可信播放器信号会计入观看时长。</span>
              <button onClick={() => void finishVideo(video)}>
                <Check size={15} />
                完成本次学习
              </button>
            </footer>
          </section>
        </div>
      )}

      {inboxVideo && (
        <div
          className="dialog-backdrop"
          onMouseDown={() => setInboxVideo(null)}
        >
          <section
            className="student-video-dialog"
            role="dialog"
            aria-modal="true"
            aria-label={resourceText(
              inboxVideo.resource,
              "title",
              "定向教学视频",
            )}
            onMouseDown={(event) => event.stopPropagation()}
          >
            <header>
              <div>
                <small>
                  资源收件箱 ·{" "}
                  {inboxVideo.personalized ? "为我定制" : "教师通用资源"}
                </small>
                <h3>
                  {resourceText(inboxVideo.resource, "title", "定向教学视频")}
                </h3>
              </div>
              <button
                aria-label="关闭定向视频"
                onClick={() => setInboxVideo(null)}
              >
                <X size={18} />
              </button>
            </header>
            <div>
              {typeof inboxVideo.resource.embed_url === "string" &&
              inboxVideo.resource.embed_url ? (
                <iframe
                  src={inboxVideo.resource.embed_url}
                  title={resourceText(
                    inboxVideo.resource,
                    "title",
                    "定向教学视频",
                  )}
                  allow="fullscreen; picture-in-picture"
                />
              ) : (
                <div className="video-preview-fallback">
                  <Video size={42} />
                  <p>该视频资源未提供可嵌入播放器，请打开已核验来源页。</p>
                  <a
                    href={resourceText(
                      inboxVideo.resource,
                      "url",
                      resourceText(inboxVideo.resource, "canonical_url", "#"),
                    )}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <ExternalLink size={16} />
                    打开来源页
                  </a>
                </div>
              )}
            </div>
            <footer>
              <span>已记录收件箱打开事件。</span>
              {!inboxVideo.completed_at && (
                <button
                  disabled={resourceBusy}
                  onClick={() => void completeInbox(inboxVideo)}
                >
                  <Check size={15} />
                  标记完成
                </button>
              )}
            </footer>
          </section>
        </div>
      )}
    </div>
  );
}
