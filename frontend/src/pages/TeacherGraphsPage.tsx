import {
  AlertTriangle,
  ArrowRight,
  Check,
  CheckCircle2,
  FilePenLine,
  FileText,
  GitBranch,
  Network,
  Pencil,
  Plus,
  RefreshCw,
  Send,
  ShieldCheck,
  Sparkles,
  Trash2,
  Undo2,
  Upload,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError } from "../errors";
import { useApi } from "../RuntimeContext";
import { useDialogs, useUnsavedChanges } from "../components/Dialogs";
import AudienceDialog, {
  type PublishResource,
} from "../components/AudienceDialog";
import GraphEditorDialog from "../components/GraphEditorDialog";
import KnowledgeGraphView from "../components/KnowledgeGraphView";
import { ErrorState, LoadingState, Surface } from "../components/Primitives";
import { useCourse } from "../CourseContext";
import type {
  AlignmentMention,
  AlignmentRun,
  AssetPurpose,
  GraphExtractionArtifact,
  GraphExtractionProposal,
  GraphListItem,
  GraphSemanticReviewArtifact,
  GraphSemanticReviewIssue,
  KnowledgeGraph,
  ModelProfile,
} from "../types";

const ACCEPT = ".pdf,.docx,.pptx,.txt";

function errorMessage(reason: unknown, fallback = "操作失败") {
  return reason instanceof ApiError ? reason.message : fallback;
}

export default function TeacherGraphsPage() {
  const api = useApi();
  const { courseId } = useCourse();
  const dialogs = useDialogs();
  const [publishResource, setPublishResource] =
    useState<PublishResource | null>(null);
  const graphEpoch = useRef(0);
  const [items, setItems] = useState<GraphListItem[] | null>(null);
  const [graph, setGraph] = useState<KnowledgeGraph | null>(null);
  const [title, setTitle] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [sourceOpen, setSourceOpen] = useState(false);
  const [sourceMode, setSourceMode] = useState<"file" | "text">("file");
  const [sourceFile, setSourceFile] = useState<File | null>(null);
  const [sourceText, setSourceText] = useState("");
  const [sourceBusy, setSourceBusy] = useState(false);
  const closeSource = async () => {
    if (sourceBusy || extractionBusy) return;
    if (
      !alignment &&
      (sourceText.trim() || sourceFile) &&
      !(await dialogs.confirm(
        "关闭教学材料",
        "当前材料内容将保留在工作区，是否返回图谱？",
      ))
    )
      return;
    setSourceOpen(false);
  };
  const [sourceStage, setSourceStage] = useState("");
  const [alignment, setAlignment] = useState<AlignmentRun | null>(null);
  useUnsavedChanges(
    sourceOpen && Boolean(sourceText.trim() || sourceFile) && !alignment,
  );
  const [novelConceptNames, setNovelConceptNames] = useState<
    Record<string, string>
  >({});
  const [modelProfiles, setModelProfiles] = useState<ModelProfile[]>([]);
  const [selectedProfileId, setSelectedProfileId] = useState("");
  const [extraction, setExtraction] = useState<GraphExtractionArtifact | null>(
    null,
  );
  const [extractionBusy, setExtractionBusy] = useState(false);
  const [extractionStage, setExtractionStage] = useState("");
  const [reviewPanelOpen, setReviewPanelOpen] = useState(false);
  const [reviewProfiles, setReviewProfiles] = useState<ModelProfile[]>([]);
  const [selectedReviewProfileId, setSelectedReviewProfileId] = useState("");
  const [semanticReview, setSemanticReview] =
    useState<GraphSemanticReviewArtifact | null>(null);
  const [reviewBusy, setReviewBusy] = useState(false);
  const [reviewStage, setReviewStage] = useState("");
  const [editorOpen, setEditorOpen] = useState(false);
  const [editorNodeId, setEditorNodeId] = useState<string | null>(null);
  const extractionKey = useRef("");
  const semanticReviewKey = useRef("");
  const fileInput = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setItems(null);
    setGraph(null);
    setError("");
    try {
      const rows = await api.teacherGraphs(courseId);
      setItems(rows);
      if (rows[0]) setGraph(await api.teacherGraph(rows[0].id));
    } catch (reason) {
      setError(errorMessage(reason, "无法读取图谱工作区"));
    }
  }, [courseId]);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (
    action: () => Promise<KnowledgeGraph>,
    message: string,
  ) => {
    setBusy(true);
    setError("");
    try {
      const result = await action();
      setGraph(result);
      setNotice(message);
      setItems(await api.teacherGraphs(courseId));
      return true;
    } catch (reason) {
      setError(errorMessage(reason));
      return false;
    } finally {
      setBusy(false);
    }
  };

  const sourcePurpose: AssetPurpose =
    graph?.mode === "new" ? "graph_build" : "graph_update";
  const matchedCount =
    alignment?.mentions.filter((item) => item.status === "matched").length ?? 0;
  const pendingCount =
    alignment?.mentions.filter((item) => item.review?.status === "pending")
      .length ?? 0;
  const alignedIds = useMemo(
    () => new Set(graph?.nodes.map((node) => node.concept_id) ?? []),
    [graph],
  );
  const selectedGraphItem = items?.find((item) => item.id === graph?.id);

  const renameGraph = async () => {
    if (!graph) return;
    const nextTitle = (await dialogs.prompt("重命名图谱", graph.title))?.trim();
    if (!nextTitle || nextTitle === graph.title) return;
    await act(() => api.renameGraph(graph.id, nextTitle), "图谱名称已更新");
  };

  const discardDraft = async () => {
    if (
      !graph ||
      !(await dialogs.confirm(
        "放弃更新草稿",
        "放弃后恢复已发布版本，此操作无法撤销。",
        true,
      ))
    )
      return;
    await act(
      () => api.discardGraphDraft(graph.id, graph.version),
      "更新草稿已放弃，已恢复到发布版本",
    );
  };

  const deleteGraph = async () => {
    if (
      !graph ||
      !(await dialogs.confirm(
        "删除未发布图谱",
        "删除“" + graph.title + "”后无法恢复。",
        true,
      ))
    )
      return;
    setBusy(true);
    setError("");
    try {
      await api.deleteGraph(graph.id, graph.version);
      setGraph(null);
      setNotice("未发布图谱已删除");
      setItems(await api.teacherGraphs(courseId));
    } catch (reason) {
      setError(errorMessage(reason, "图谱删除失败"));
    } finally {
      setBusy(false);
    }
  };

  const openSource = () => {
    setSourceOpen(true);
    setSourceMode("file");
    // Retain material input when returning from the graph.
    extractionKey.current = "";
    setSourceStage("");
    setError("");
    void api
      .modelProfiles("a2.graph_extract")
      .then((profiles) => {
        setModelProfiles(profiles);
        setSelectedProfileId(
          (current) =>
            current ||
            profiles.find((item) => item.available)?.id ||
            profiles[0]?.id ||
            "",
        );
      })
      .catch((reason) => setError(errorMessage(reason, "无法读取模型配置")));
  };

  const startAlignment = async () => {
    if (!graph || graph.revision_status !== "draft") return;
    setSourceBusy(true);
    setError("");
    try {
      let result: AlignmentRun;
      if (sourceMode === "file" && sourceFile) {
        setSourceStage("正在建立安全上传通道…");
        const prepared = await api.prepareAsset(
          courseId,
          sourceFile,
          sourcePurpose,
        );
        setSourceStage("正在上传并校验文件…");
        await api.uploadAssetContent(prepared.upload_url, sourceFile);
        setSourceStage("正在解析文档结构与证据位置…");
        await api.completeAsset(courseId, prepared.asset.id);
        setSourceStage("正在与当前课程知识点对齐…");
        result = await api.createAlignmentRun(courseId, {
          source_asset_id: prepared.asset.id,
          purpose: sourcePurpose,
        });
      } else {
        setSourceStage("正在解析描述并与课程知识点对齐…");
        result = await api.createAlignmentRun(courseId, {
          manual_text: sourceText,
          purpose: sourcePurpose,
        });
      }
      setAlignment(result);
      sessionStorage.setItem("zhixue-session:alignment:" + courseId, result.id);
      setNovelConceptNames({});
      setExtraction(null);
      extractionKey.current = "";
      setSourceStage("");
    } catch (reason) {
      setError(errorMessage(reason, "材料解析失败"));
      setSourceStage("");
    } finally {
      setSourceBusy(false);
    }
  };

  const decide = async (mention: AlignmentMention, conceptId?: string) => {
    if (!mention.review) return;
    setSourceBusy(true);
    setError("");
    try {
      const updated = await api.decideAlignment(
        mention.review.id,
        conceptId
          ? { decision: "matched", selected_concept_id: conceptId }
          : { decision: "abstained", note: "教师确认暂不纳入当前课程图谱" },
      );
      setAlignment(updated);
    } catch (reason) {
      setError(errorMessage(reason, "复核结果保存失败"));
    } finally {
      setSourceBusy(false);
    }
  };

  const createNovelConcept = async (mention: AlignmentMention) => {
    if (!mention.review) return;
    const name = (novelConceptNames[mention.id] ?? mention.raw_text).trim();
    if (name.length < 2) return;
    setSourceBusy(true);
    setError("");
    try {
      const updated = await api.decideAlignment(mention.review.id, {
        decision: "created",
        new_concept_name: name,
        note: "教师确认为当前课程的新规范概念",
      });
      setAlignment(updated);
    } catch (reason) {
      setError(errorMessage(reason, "新概念创建失败"));
    } finally {
      setSourceBusy(false);
    }
  };

  const conceptForMention = (mention: AlignmentMention) => {
    if (
      mention.review?.status === "decided" &&
      mention.review.decision === "abstained"
    )
      return undefined;
    const selected = mention.review?.selected_concept_id;
    return (
      mention.candidates.find((item) => item.concept_id === selected) ??
      mention.candidates.find((item) => item.recommended) ??
      mention.candidates[0]
    );
  };

  const applyAlignment = async () => {
    if (!graph || !alignment) return;
    const success = await act(
      () => api.applyAlignment(graph.id, alignment.id, graph.version),
      "已将通过对齐的知识点加入当前图谱",
    );
    if (success) {
      setSourceOpen(false);
      setSourceFile(null);
      setSourceText("");
      setAlignment(null);
      setExtraction(null);
    }
  };

  const selectedProfile = modelProfiles.find(
    (item) => item.id === selectedProfileId,
  );
  const selectedReviewProfile = reviewProfiles.find(
    (item) => item.id === selectedReviewProfileId,
  );

  const startExtraction = async () => {
    if (
      !graph ||
      !alignment ||
      !selectedProfile?.available ||
      alignment.source_type !== "asset"
    )
      return;
    setExtractionBusy(true);
    setError("");
    setExtractionStage("正在调用所选模型提取知识结构…");
    try {
      if (!extractionKey.current) {
        extractionKey.current = `graph-extract:${graph.id}:${alignment.id}:${selectedProfile.id}:${crypto.randomUUID()}`;
      }
      const result = await api.extractGraphCandidates(graph.id, {
        alignment_run_id: alignment.id,
        requested_profile_id: selectedProfile.id,
        idempotency_key: extractionKey.current,
        expected_revision_version: graph.version,
      });
      setExtraction(result);
      setExtractionStage("");
    } catch (reason) {
      setError(errorMessage(reason, "图谱结构抽取失败"));
      setExtractionStage("");
    } finally {
      setExtractionBusy(false);
    }
  };

  const decideExtraction = async (
    proposal: GraphExtractionProposal,
    decision: "accepted" | "rejected",
  ) => {
    if (!extraction) return;
    setExtractionBusy(true);
    setError("");
    try {
      setExtraction(
        await api.decideGraphExtraction(extraction.id, proposal.id, {
          decision,
          expected_artifact_version: extraction.version,
          note:
            decision === "accepted"
              ? "教师核对来源证据后接受"
              : "教师确认暂不写入当前图谱",
        }),
      );
    } catch (reason) {
      setError(errorMessage(reason, "候选复核结果保存失败"));
    } finally {
      setExtractionBusy(false);
    }
  };

  const applyExtraction = async () => {
    if (!graph || !extraction) return;
    setExtractionBusy(true);
    setError("");
    try {
      await api.applyGraphExtraction(
        extraction.id,
        extraction.version,
        graph.version,
      );
      setGraph(await api.teacherGraph(graph.id));
      setItems(await api.teacherGraphs(courseId));
      setNotice("AI候选经教师复核后已写入当前图谱草稿");
      setSourceOpen(false);
      setSourceFile(null);
      setSourceText("");
      setAlignment(null);
      setExtraction(null);
    } catch (reason) {
      setError(errorMessage(reason, "候选写入失败"));
    } finally {
      setExtractionBusy(false);
    }
  };

  const openSemanticReview = async () => {
    if (!graph) return;
    setReviewPanelOpen(true);
    setError("");
    if (reviewProfiles.length) return;
    setReviewBusy(true);
    setReviewStage("正在读取语义预审模型配置…");
    try {
      const profiles = await api.modelProfiles("a2.graph_semantic_review");
      setReviewProfiles(profiles);
      setSelectedReviewProfileId(
        (current) =>
          current ||
          profiles.find((item) => item.available)?.id ||
          profiles[0]?.id ||
          "",
      );
      setReviewStage("");
    } catch (reason) {
      setError(errorMessage(reason, "无法读取语义预审模型配置"));
      setReviewStage("");
    } finally {
      setReviewBusy(false);
    }
  };

  const startSemanticReview = async () => {
    if (!graph || !selectedReviewProfile?.available) return;
    setReviewBusy(true);
    setReviewStage("正在进行受限语义预审…");
    setError("");
    try {
      if (!semanticReviewKey.current) {
        semanticReviewKey.current = `graph-semantic-review:${graph.id}:${selectedReviewProfile.id}:${crypto.randomUUID()}`;
      }
      const result = await api.createGraphSemanticReview(graph.id, {
        requested_profile_id: selectedReviewProfile.id,
        idempotency_key: semanticReviewKey.current,
        expected_revision_version: graph.version,
      });
      setSemanticReview(result);
      setReviewStage("");
    } catch (reason) {
      setError(errorMessage(reason, "语义预审失败"));
      setReviewStage("");
    } finally {
      setReviewBusy(false);
    }
  };

  const decideSemanticIssue = async (
    issue: GraphSemanticReviewIssue,
    decision: "confirmed" | "ignored",
  ) => {
    if (!semanticReview) return;
    setReviewBusy(true);
    setError("");
    try {
      setSemanticReview(
        await api.decideGraphSemanticReview(semanticReview.id, issue.id, {
          decision,
          expected_artifact_version: semanticReview.version,
          note:
            decision === "confirmed"
              ? "教师确认需要后续编辑处理"
              : "教师确认该提示暂不影响当前发布",
        }),
      );
    } catch (reason) {
      setError(errorMessage(reason, "语义预审处置失败"));
    } finally {
      setReviewBusy(false);
    }
  };

  if (error && !items)
    return <ErrorState message={error} retry={() => void load()} />;
  if (!items) return <LoadingState label="正在读取知识图谱工作区…" />;

  return (
    <div className="teacher-graph-page">
      <section className="teacher-graph-hero">
        <div>
          <span>
            <GitBranch size={15} />
            知识结构工作区
          </span>
          <h2>知识图谱构建</h2>
          <p>
            从教学材料识别知识点，保留来源证据，经教师编辑与结构校验后发布。
          </p>
        </div>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (title.trim())
              void act(
                () => api.createGraph(courseId, title.trim()),
                "已创建空白图谱工作区",
              );
          }}
        >
          <input
            aria-label="新图谱名称"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="输入新图谱名称"
          />
          <button disabled={busy || !title.trim()}>
            <Plus size={16} />
            新建图谱
          </button>
        </form>
      </section>
      {error && (
        <div className="inline-error">
          <AlertTriangle size={15} />
          {error}
        </div>
      )}
      {notice && (
        <div className="inline-notice">
          <CheckCircle2 size={15} />
          {notice}
        </div>
      )}
      <div className="teacher-graph-layout">
        <Surface className="teacher-graph-list">
          <header>
            <h3>已有图谱</h3>
            <span>{items.length}</span>
          </header>
          {items.map((item) => (
            <button
              disabled={busy}
              className={graph?.id === item.id ? "active" : ""}
              key={item.id}
              onClick={async () => {
                const epoch = ++graphEpoch.current;
                setBusy(true);
                setError("");
                try {
                  const next = await api.teacherGraph(item.id);
                  if (epoch !== graphEpoch.current) return;
                  setGraph(next);
                  setReviewPanelOpen(false);
                  setSemanticReview(null);
                  semanticReviewKey.current = "";
                } catch (reason) {
                  setError(errorMessage(reason, "无法读取图谱"));
                } finally {
                  if (epoch === graphEpoch.current) setBusy(false);
                }
              }}
            >
              <GitBranch size={16} />
              <div>
                <b>{item.title}</b>
                <small>
                  {item.node_count}个知识点 · {item.edge_count}条关系
                </small>
              </div>
              <em>{item.status === "published" ? "已发布" : "草稿"}</em>
            </button>
          ))}
        </Surface>
        <Surface className="teacher-graph-workspace">
          {!graph ? (
            <div className="graph-empty">
              <GitBranch size={30} />
              <h3>
                {items.length
                  ? "选择一份图谱开始查看"
                  : "当前课程还没有知识图谱"}
              </h3>
              <p>也可以在上方输入名称创建新的空白工作区。</p>
            </div>
          ) : (
            <>
              <header>
                <div>
                  <small>
                    {graph.revision_status === "published"
                      ? "已发布版本"
                      : "教师编辑工作区"}
                  </small>
                  <h3>{graph.title}</h3>
                </div>
                <div>
                  <button
                    className="icon-only"
                    aria-label="重命名图谱"
                    disabled={busy}
                    title="重命名图谱"
                    onClick={() => void renameGraph()}
                  >
                    <FilePenLine size={15} />
                  </button>
                  {graph.revision_status === "published" ? (
                    <>
                      <button
                        disabled={busy}
                        onClick={() =>
                          setPublishResource({
                            id: graph.id,
                            type: "graph",
                            version: graph.revision_no,
                            title: graph.title,
                            concepts: graph.nodes.map((n) => ({
                              id: n.concept_id,
                              label: n.label,
                            })),
                          })
                        }
                      >
                        <Send size={15} />
                        选择接收者
                      </button>
                      <button
                        disabled={busy}
                        onClick={() =>
                          void act(
                            () => api.createGraphRevision(graph.id),
                            "已创建增量更新工作区",
                          )
                        }
                      >
                        <RefreshCw size={15} />
                        更新图谱
                      </button>
                    </>
                  ) : (
                    <>
                      {selectedGraphItem?.published_revision_id ? (
                        <button
                          className="icon-only"
                          aria-label="放弃更新草稿"
                          disabled={busy}
                          title="放弃更新草稿"
                          onClick={() => void discardDraft()}
                        >
                          <Undo2 size={15} />
                        </button>
                      ) : (
                        <button
                          className="icon-only"
                          aria-label="删除未发布图谱"
                          disabled={busy}
                          title="删除未发布图谱"
                          onClick={() => void deleteGraph()}
                        >
                          <Trash2 size={15} />
                        </button>
                      )}
                      <button
                        onClick={() => {
                          setEditorNodeId(null);
                          setEditorOpen(true);
                        }}
                      >
                        <Pencil size={15} />
                        编辑图谱
                      </button>
                      <button onClick={openSource}>
                        <Sparkles size={15} />
                        导入教学材料
                      </button>
                      <button
                        disabled={busy}
                        onClick={() =>
                          void act(
                            () => api.validateGraph(graph.id, graph.version),
                            "结构与来源校验已完成",
                          )
                        }
                      >
                        <ShieldCheck size={15} />
                        校验图谱
                      </button>
                      <button onClick={() => void openSemanticReview()}>
                        <Network size={15} />
                        AI语义预审
                      </button>
                      <button
                        className="primary"
                        disabled={busy}
                        onClick={() =>
                          void act(
                            () => api.publishGraph(graph.id, graph.version),
                            "图谱发布版本已保存，可继续选择接收者",
                          )
                        }
                      >
                        <Send size={15} />
                        发布图谱
                      </button>
                    </>
                  )}
                </div>
              </header>
              <KnowledgeGraphView
                graph={graph}
                onNodeClick={
                  graph.revision_status === "draft"
                    ? (node) => {
                        setEditorNodeId(node.id);
                        setEditorOpen(true);
                      }
                    : undefined
                }
              />
              {graph.quality && (
                <div
                  className={`quality-strip ${graph.quality.hard_pass ? "pass" : "fail"}`}
                >
                  <ShieldCheck size={16} />
                  <b>
                    {graph.quality.hard_pass
                      ? "结构检查通过"
                      : "存在需要修正的问题"}
                  </b>
                  <span>
                    质量分 {Math.round(graph.quality.quality_score)} ·{" "}
                    {graph.quality.metrics.node_count}个节点 ·{" "}
                    {graph.quality.metrics.edge_count}条关系 · 来源覆盖{" "}
                    {Math.round(
                      (graph.quality.metrics.provenance_coverage ?? 0) * 100,
                    )}
                    %
                  </span>
                </div>
              )}
            </>
          )}
        </Surface>
      </div>

      {publishResource && (
        <AudienceDialog
          courseId={courseId}
          resource={publishResource}
          onClose={() => setPublishResource(null)}
          onPublished={setNotice}
        />
      )}
      {editorOpen && graph && graph.revision_status === "draft" && (
        <GraphEditorDialog
          graph={graph}
          initialNodeId={editorNodeId}
          onClose={() => setEditorOpen(false)}
          onSaved={(updated, message) => {
            setGraph(updated);
            setNotice(message);
            setSemanticReview(null);
            semanticReviewKey.current = "";
            void api.teacherGraphs(courseId).then(setItems);
          }}
        />
      )}

      {reviewPanelOpen && graph && (
        <div className="dialog-backdrop" role="presentation">
          <section
            className="semantic-review-dialog"
            role="dialog"
            aria-modal="true"
            aria-label="AI语义预审"
          >
            <header>
              <div>
                <span>受限语义预审</span>
                <h3>{graph.title}</h3>
                <p>
                  模型只提出可复核的问题清单，教师决定是否采纳，不直接修改图谱。
                </p>
              </div>
              <button
                aria-label="关闭"
                onClick={() => setReviewPanelOpen(false)}
              >
                <X size={17} />
              </button>
            </header>
            {!semanticReview ? (
              <div className="semantic-review-setup">
                <label>
                  <span>选择模型</span>
                  <select
                    aria-label="选择模型"
                    value={selectedReviewProfileId}
                    onChange={(event) => {
                      setSelectedReviewProfileId(event.target.value);
                      semanticReviewKey.current = "";
                    }}
                  >
                    {reviewProfiles.map((profile) => (
                      <option
                        key={profile.id}
                        value={profile.id}
                        disabled={!profile.available}
                      >
                        {profile.display_name}
                        {profile.available ? "" : " · 当前不可用"}
                      </option>
                    ))}
                  </select>
                </label>
                <div
                  className={
                    "profile-feasibility " +
                    (selectedReviewProfile?.available ? "available" : "")
                  }
                >
                  {selectedReviewProfile?.available ? (
                    <>
                      <CheckCircle2 size={15} />
                      <span>可执行语义预审；结果受当前图谱版本约束</span>
                    </>
                  ) : (
                    <>
                      <AlertTriangle size={15} />
                      <span>
                        {selectedReviewProfile?.unavailable_reason ||
                          "正在读取模型可用性"}
                      </span>
                    </>
                  )}
                </div>
                <button
                  className="semantic-review-action"
                  disabled={
                    reviewBusy ||
                    !selectedReviewProfile?.available ||
                    graph.nodes.length === 0
                  }
                  onClick={() => void startSemanticReview()}
                >
                  <Network size={16} />
                  开始语义预审
                </button>
                <div className="semantic-review-boundary">
                  <span>
                    <b>{graph.nodes.length}</b>节点
                  </span>
                  <span>
                    <b>{graph.edges.length}</b>关系
                  </span>
                  <span>
                    <b>{graph.version}</b>当前版本
                  </span>
                </div>
              </div>
            ) : (
              <div className="semantic-review-result">
                <div
                  className={"semantic-review-summary " + semanticReview.status}
                >
                  <span>
                    <b>
                      {String(
                        semanticReview.summary.issue_count ??
                          semanticReview.issues.length,
                      )}
                    </b>
                    预审问题
                  </span>
                  <span>
                    <b>{String(semanticReview.summary.warning_count ?? 0)}</b>
                    提醒项
                  </span>
                </div>
                <div className="semantic-review-issues">
                  {semanticReview.issues.length === 0 && (
                    <div className="semantic-review-empty">
                      <CheckCircle2 size={24} />
                      <b>未发现需要处理的语义问题</b>
                      <span>当前结果仍建议由教师结合课堂目标确认。</span>
                    </div>
                  )}
                  {semanticReview.issues.map((issue) => (
                    <article
                      key={issue.id}
                      className={issue.severity + " " + issue.status}
                    >
                      <div className="semantic-review-severity">
                        {issue.severity === "error"
                          ? "阻断"
                          : issue.severity === "warning"
                            ? "提醒"
                            : "信息"}
                      </div>
                      <div className="semantic-review-main">
                        <b>{issue.target_label || issue.target_id}</b>
                        <p>{issue.claim}</p>
                        {issue.suggestion && <small>{issue.suggestion}</small>}
                      </div>
                      <div className="semantic-review-meta">
                        <span>{Math.round(issue.confidence * 100)}%</span>
                        <em>
                          {issue.evidence_span_ids.length
                            ? issue.evidence_span_ids.length + "处证据"
                            : "无外部证据引用"}
                        </em>
                      </div>
                      {issue.status === "pending" ? (
                        <div className="semantic-review-actions">
                          <button
                            disabled={reviewBusy}
                            onClick={() =>
                              void decideSemanticIssue(issue, "ignored")
                            }
                          >
                            <X size={14} />
                            忽略
                          </button>
                          <button
                            className="confirm"
                            disabled={reviewBusy}
                            onClick={() =>
                              void decideSemanticIssue(issue, "confirmed")
                            }
                          >
                            <Check size={14} />
                            确认
                          </button>
                        </div>
                      ) : (
                        <em className="semantic-review-status">
                          {issue.status === "confirmed" ? "已确认" : "已忽略"}
                        </em>
                      )}
                    </article>
                  ))}
                </div>
              </div>
            )}
            <footer>
              <div>
                {reviewBusy && (
                  <span className="source-progress">
                    <RefreshCw size={14} />
                    {reviewStage || "正在保存预审结果…"}
                  </span>
                )}
              </div>
              <div>
                {semanticReview && (
                  <button
                    onClick={() => {
                      setSemanticReview(null);
                      semanticReviewKey.current = "";
                    }}
                  >
                    重新预审
                  </button>
                )}
                <button
                  className="primary"
                  onClick={() => setReviewPanelOpen(false)}
                >
                  完成
                </button>
              </div>
            </footer>
          </section>
        </div>
      )}

      {sourceOpen && graph && (
        <div className="dialog-backdrop" role="presentation">
          <section
            className="teacher-source-dialog"
            role="dialog"
            aria-modal="true"
            aria-label="导入教学材料"
          >
            <header>
              <div>
                <span>材料驱动的知识点对齐</span>
                <h3>{graph.title}</h3>
                <p>
                  优先匹配当前课程知识点；未匹配概念须经教师确认后才能进入草稿。
                </p>
              </div>
              <button aria-label="关闭" onClick={() => void closeSource()}>
                <X size={17} />
              </button>
            </header>
            {!alignment ? (
              <div className="source-intake-body">
                <div className="source-mode-tabs">
                  <button
                    className={sourceMode === "file" ? "active" : ""}
                    onClick={() => setSourceMode("file")}
                  >
                    <Upload size={15} />
                    上传教学文件
                  </button>
                  <button
                    className={sourceMode === "text" ? "active" : ""}
                    onClick={() => setSourceMode("text")}
                  >
                    <FileText size={15} />
                    输入自然语言
                  </button>
                </div>
                {sourceMode === "file" ? (
                  <button
                    className={`source-dropzone ${sourceFile ? "selected" : ""}`}
                    onClick={() => fileInput.current?.click()}
                  >
                    <input
                      ref={fileInput}
                      type="file"
                      accept={ACCEPT}
                      onChange={(event) =>
                        setSourceFile(event.target.files?.[0] ?? null)
                      }
                    />
                    {sourceFile ? (
                      <>
                        <CheckCircle2 size={26} />
                        <b>{sourceFile.name}</b>
                        <span>
                          {(sourceFile.size / 1024).toFixed(1)} KB ·
                          点击可重新选择
                        </span>
                      </>
                    ) : (
                      <>
                        <Upload size={27} />
                        <b>选择课程讲义或课件</b>
                        <span>支持 PDF、DOCX、PPTX、TXT，单份不超过 20 MB</span>
                      </>
                    )}
                  </button>
                ) : (
                  <label className="source-text-input">
                    <span>描述需要构建或补充的知识内容</span>
                    <textarea
                      aria-label="描述需要构建或补充的知识内容"
                      value={sourceText}
                      onChange={(event) => setSourceText(event.target.value)}
                      placeholder="例如：补充正则化、过拟合与模型泛化之间的关系；重点保留正则化与损失函数的联系。"
                    />
                    <small>{sourceText.length}/12000</small>
                  </label>
                )}
                <div className="source-policy-row">
                  <span>
                    <ShieldCheck size={16} />
                    <b>安全解析</b>
                    <small>不执行宏、脚本或外部链接</small>
                  </span>
                  <span>
                    <GitBranch size={16} />
                    <b>课程内对齐</b>
                    <small>歧义结果不会被强制匹配</small>
                  </span>
                  <span>
                    <FileText size={16} />
                    <b>证据可追溯</b>
                    <small>保留页码、幻灯片或段落位置</small>
                  </span>
                </div>
              </div>
            ) : (
              <div className="alignment-result-body">
                <div className="alignment-summary">
                  <span>
                    <b>{alignment.summary.mention_count ?? 0}</b>识别知识点
                  </span>
                  <span className="success">
                    <b>{matchedCount}</b>已对齐
                  </span>
                  <span className={pendingCount ? "warning" : "success"}>
                    <b>{pendingCount}</b>待复核
                  </span>
                  <em>
                    {alignment.source_type === "asset"
                      ? "材料证据已保留"
                      : "按输入顺序处理"}
                  </em>
                </div>
                <div className="alignment-list">
                  {alignment.mentions.length === 0 && (
                    <div className="alignment-empty">
                      <AlertTriangle size={22} />
                      <b>没有可写入的知识点</b>
                      <span>请补充课程概念描述后重新识别。</span>
                    </div>
                  )}
                  {alignment.mentions.map((mention) => {
                    const selected = conceptForMention(mention);
                    return (
                      <article
                        key={mention.id}
                        className={`alignment-row ${mention.status}`}
                      >
                        <div className="alignment-source">
                          <span>
                            {mention.ordinal.toString().padStart(2, "0")}
                          </span>
                          <div>
                            <b>{mention.raw_text}</b>
                            <small>
                              {mention.evidence_span_id
                                ? "已绑定原文证据"
                                : "自然语言输入"}
                            </small>
                          </div>
                        </div>
                        <ArrowRight size={15} />
                        {mention.review?.status === "pending" ? (
                          <div className="alignment-review-options">
                            {mention.candidates.slice(0, 3).map((candidate) => (
                              <button
                                disabled={sourceBusy}
                                key={candidate.concept_id}
                                onClick={() =>
                                  void decide(mention, candidate.concept_id)
                                }
                              >
                                <b>{candidate.concept_name}</b>
                                <span>
                                  {Math.round(candidate.final_score * 100)}%
                                </span>
                              </button>
                            ))}
                            <div className="alignment-new-concept">
                              <input
                                aria-label={`为${mention.raw_text}创建课程规范概念`}
                                value={
                                  novelConceptNames[mention.id] ??
                                  mention.raw_text
                                }
                                maxLength={120}
                                onChange={(event) =>
                                  setNovelConceptNames((current) => ({
                                    ...current,
                                    [mention.id]: event.target.value,
                                  }))
                                }
                              />
                              <button
                                disabled={
                                  sourceBusy ||
                                  (
                                    novelConceptNames[mention.id] ??
                                    mention.raw_text
                                  ).trim().length < 2
                                }
                                onClick={() => void createNovelConcept(mention)}
                              >
                                <Plus size={13} />
                                新概念
                              </button>
                            </div>
                            <button
                              className="abstain"
                              disabled={sourceBusy}
                              onClick={() => void decide(mention)}
                            >
                              暂不纳入
                            </button>
                          </div>
                        ) : (
                          <div
                            className={`alignment-target ${selected ? "" : "abstained"}`}
                          >
                            <span>
                              {selected ? <Check size={14} /> : <X size={14} />}
                            </span>
                            <div>
                              <b>{selected?.concept_name ?? "暂不纳入"}</b>
                              <small>
                                {selected
                                  ? `综合匹配度 ${Math.round(selected.final_score * 100)}%`
                                  : "教师已确认不映射到课程知识点"}
                              </small>
                            </div>
                            {selected &&
                              alignedIds.has(selected.concept_id) && (
                                <em>图谱中已有</em>
                              )}
                          </div>
                        )}
                      </article>
                    );
                  })}
                </div>
                <section className="model-extraction-panel">
                  <header>
                    <div>
                      <Network size={17} />
                      <span>
                        <b>AI结构抽取</b>
                        <small>模型只生成候选，须经教师逐项复核</small>
                      </span>
                    </div>
                    {extraction && (
                      <em>
                        {extraction.model_run.actual_profile_id ===
                        extraction.model_run.requested_profile_id
                          ? "按所选模型完成"
                          : "模型身份已披露"}
                      </em>
                    )}
                  </header>
                  {!extraction ? (
                    <div className="model-extraction-setup">
                      <label>
                        <span>选择模型</span>
                        <select
                          aria-label="选择模型"
                          value={selectedProfileId}
                          onChange={(event) => {
                            setSelectedProfileId(event.target.value);
                            extractionKey.current = "";
                          }}
                        >
                          {modelProfiles.map((profile) => (
                            <option
                              key={profile.id}
                              value={profile.id}
                              disabled={!profile.available}
                            >
                              {profile.display_name}
                              {profile.available ? "" : " · 当前不可用"}
                            </option>
                          ))}
                        </select>
                      </label>
                      <div
                        className={`profile-feasibility ${selectedProfile?.available ? "available" : ""}`}
                      >
                        {selectedProfile?.available ? (
                          <>
                            <CheckCircle2 size={15} />
                            <span>能力与运行配置已通过任务可行性检查</span>
                          </>
                        ) : (
                          <>
                            <AlertTriangle size={15} />
                            <span>
                              {selectedProfile?.unavailable_reason ||
                                "正在读取模型可用性"}
                            </span>
                          </>
                        )}
                      </div>
                      <button
                        className="extract-action"
                        disabled={
                          extractionBusy ||
                          alignment.source_type !== "asset" ||
                          !selectedProfile?.available
                        }
                        onClick={() => void startExtraction()}
                      >
                        <Sparkles size={16} />
                        提取知识结构
                      </button>
                      {alignment.source_type !== "asset" && (
                        <p>
                          自然语言描述可完成知识点对齐；结构关系需上传包含原文位置的教学文件。
                        </p>
                      )}
                    </div>
                  ) : (
                    <div className="model-extraction-result">
                      <div className="extraction-run-strip">
                        <span>
                          <b>
                            {modelProfiles.find(
                              (item) =>
                                item.id ===
                                extraction.model_run.actual_profile_id,
                            )?.display_name ||
                              extraction.model_run.actual_profile_id}
                          </b>
                          实际执行模型
                        </span>
                        <span>
                          <b>{extraction.proposals.length}</b>候选项
                        </span>
                      </div>
                      <div className="extraction-proposals">
                        {extraction.proposals.map((proposal) => (
                          <article
                            key={proposal.id}
                            className={proposal.status}
                          >
                            <div className="proposal-kind">
                              {proposal.proposal_kind === "concept"
                                ? "知识点"
                                : "关系"}
                            </div>
                            <div className="proposal-main">
                              <b>
                                {proposal.proposal_kind === "concept"
                                  ? proposal.concept_label
                                  : `${proposal.from_label} → ${proposal.to_label}`}
                              </b>
                              <small>
                                {proposal.proposal_kind === "concept"
                                  ? proposal.rationale
                                  : `${proposal.relation} · ${proposal.rationale || "依据材料原文抽取"}`}
                              </small>
                            </div>
                            <div className="proposal-evidence">
                              {proposal.evidence_span_ids.length}处证据 ·{" "}
                              {Math.round(proposal.confidence * 100)}%
                            </div>
                            {proposal.status === "pending" ? (
                              <div className="proposal-actions">
                                <button
                                  disabled={extractionBusy}
                                  onClick={() =>
                                    void decideExtraction(proposal, "rejected")
                                  }
                                >
                                  <X size={14} />
                                  拒绝
                                </button>
                                <button
                                  className="accept"
                                  disabled={extractionBusy}
                                  onClick={() =>
                                    void decideExtraction(proposal, "accepted")
                                  }
                                >
                                  <Check size={14} />
                                  接受
                                </button>
                              </div>
                            ) : (
                              <em>
                                {proposal.status === "accepted"
                                  ? "已接受"
                                  : "已拒绝"}
                              </em>
                            )}
                          </article>
                        ))}
                      </div>
                    </div>
                  )}
                </section>
              </div>
            )}
            {error && (
              <div className="inline-error" role="alert">
                {error}
              </div>
            )}
            <footer>
              <div>
                {(sourceBusy || extractionBusy) && (
                  <span className="source-progress">
                    <RefreshCw size={14} />
                    {sourceStage || extractionStage || "正在保存复核结果…"}
                  </span>
                )}
              </div>
              <div>
                {alignment && !extraction && (
                  <button onClick={() => setAlignment(null)}>
                    重新选择来源
                  </button>
                )}
                {!alignment ? (
                  <button
                    className="primary"
                    disabled={
                      sourceBusy ||
                      (sourceMode === "file" ? !sourceFile : !sourceText.trim())
                    }
                    onClick={() => void startAlignment()}
                  >
                    <Sparkles size={15} />
                    开始识别与对齐
                  </button>
                ) : extraction ? (
                  <button
                    className="primary"
                    disabled={
                      extractionBusy || extraction.status !== "ready_to_apply"
                    }
                    onClick={() => void applyExtraction()}
                  >
                    <GitBranch size={15} />
                    应用已复核结构
                  </button>
                ) : (
                  <button
                    className="primary"
                    disabled={
                      sourceBusy || matchedCount === 0 || pendingCount > 0
                    }
                    onClick={() => void applyAlignment()}
                  >
                    <GitBranch size={15} />
                    仅加入知识点
                  </button>
                )}
              </div>
            </footer>
          </section>
        </div>
      )}
    </div>
  );
}
