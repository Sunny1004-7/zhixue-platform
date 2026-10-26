import { ApiError } from "./errors";
import type {
  Course,
  CrossCourseSummary,
  AlignmentRun,
  AssetPurpose,
  GraphListItem,
  GraphEvidenceBundle,
  GraphExtractionArtifact,
  GraphSemanticReviewArtifact,
  KnowledgeGraph,
  ModelProfile,
  CompilePracticeBlueprintPayload,
  GenerateQuestionSetPayload,
  PracticeAttemptResult,
  PracticeBlueprint,
  PracticeScore,
  QuestionSetDetail,
  QuestionSetList,
  QuestionSetProgress,
  RevealedHint,
  Role,
  StudentCourseOverview,
  TeacherCourseOverview,
  SourceAsset,
  ParsedDocument,
  UpdateQuestionPayload,
  User,
  AudienceDraft,
  DecisionSnapshot,
  AudiencePublication,
  PersonalizedResourceJob,
  ResourceInboxItem,
  StudentAttentionList,
  StudentLearningState,
  TutorConversation,
  TutorConversationItem,
  TutorExperience,
  TutorMemory,
  TutorMode,
  TutorTurn,
  VideoCandidate,
  VideoPublication,
  VideoSearchJob,
  VideoSearchSources,
} from "./types";

const API_BASE =
  import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1";
const TOKEN_KEY = "zhixing-access-token";

function uploadMime(file: File) {
  if (file.type) return file.type;
  const extension = file.name.split(".").pop()?.toLowerCase();
  return (
    (
      {
        pdf: "application/pdf",
        docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        pptx: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        txt: "text/plain",
      } as Record<string, string>
    )[extension ?? ""] ?? "application/octet-stream"
  );
}

export { ApiError } from "./errors";

function token() {
  return window.sessionStorage.getItem(TOKEN_KEY);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (typeof init.body === "string" && !headers.has("Content-Type"))
    headers.set("Content-Type", "application/json");
  const accessToken = token();
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  const resolvedBase = new URL(API_BASE, window.location.origin);
  const endpoint = path.startsWith("/api/v1/")
    ? `${resolvedBase.origin}${path}`
    : `${API_BASE}${path}`;
  const response = await fetch(endpoint, { ...init, headers });
  if (!response.ok) {
    let message = "请求失败，请稍后重试";
    let code: string | null = null;
    try {
      const payload = (await response.json()) as {
        detail?: string | { code?: string; message?: string };
      };
      if (typeof payload.detail === "string") message = payload.detail;
      else if (payload.detail) {
        if (payload.detail.message) message = payload.detail.message;
        code = payload.detail.code ?? null;
      }
    } catch {
      // Preserve the concise fallback message for non-JSON failures.
    }
    throw new ApiError(response.status, message, code);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  async login(account: string, password: string, role: Role) {
    const payload = await request<{
      access_token: string;
      expires_at: string;
      user: User;
    }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ account, password, role }),
    });
    window.sessionStorage.setItem(TOKEN_KEY, payload.access_token);
    return payload;
  },
  async logout() {
    try {
      await request<void>("/auth/logout", { method: "POST" });
    } finally {
      window.sessionStorage.removeItem(TOKEN_KEY);
      window.sessionStorage.removeItem("zhixing-course-id");
    }
  },
  me: () => request<User>("/me"),
  courses: () => request<Course[]>("/courses"),
  studentSummary: () => request<CrossCourseSummary>("/student/courses/summary"),
  studentOverview: (courseId: string) =>
    request<StudentCourseOverview>(`/student/courses/${courseId}/overview`),
  recordLearningEvent: (courseId: string, payload: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/student/courses/${courseId}/events`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  teacherOverview: (courseId: string) =>
    request<TeacherCourseOverview>(`/teacher/courses/${courseId}/overview`),
  studentQuestionSets: (courseId: string) =>
    request<QuestionSetList>(`/student/courses/${courseId}/question-sets`),
  teacherQuestionSets: (courseId: string) =>
    request<QuestionSetList>(`/teacher/courses/${courseId}/question-sets`),
  questionSet: (setId: string) =>
    request<QuestionSetDetail>(`/question-sets/${setId}`),
  compilePracticeBlueprint: (
    courseId: string,
    payload: CompilePracticeBlueprintPayload,
  ) =>
    request<PracticeBlueprint>(
      `/courses/${courseId}/practice-blueprints:compile`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  generateQuestionSet: (
    courseId: string,
    payload: GenerateQuestionSetPayload,
  ) =>
    request<QuestionSetDetail>(`/courses/${courseId}/question-sets:generate`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateTeacherQuestion: (questionId: string, payload: UpdateQuestionPayload) =>
    request<QuestionSetDetail>(`/teacher/questions/${questionId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  validateQuestionSet: (setId: string, version: number) =>
    request<QuestionSetDetail>(`/teacher/question-sets/${setId}:validate`, {
      method: "POST",
      body: JSON.stringify({ expected_revision_version: version }),
    }),
  publishQuestionSet: (setId: string, version: number) =>
    request<QuestionSetDetail>(`/teacher/question-sets/${setId}:publish`, {
      method: "POST",
      body: JSON.stringify({ expected_revision_version: version }),
    }),
  revealQuestionHint: (
    questionId: string,
    level: number,
    idempotencyKey: string,
  ) =>
    request<RevealedHint>(
      `/student/questions/${questionId}/hints/${level}:reveal`,
      {
        method: "POST",
        body: JSON.stringify({ idempotency_key: idempotencyKey }),
      },
    ),
  submitQuestionAttempt: (
    questionId: string,
    payload: {
      idempotency_key: string;
      answer: Record<string, unknown>;
      expected_revision_id: string;
    },
  ) =>
    request<PracticeAttemptResult>(
      `/student/questions/${questionId}/attempts`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  questionSetProgress: (setId: string) =>
    request<QuestionSetProgress>(`/student/question-sets/${setId}/progress`),
  attemptScore: (attemptId: string) =>
    request<PracticeScore>(`/student/attempts/${attemptId}/score`),
  studentGraphs: (courseId: string) =>
    request<GraphListItem[]>(`/student/courses/${courseId}/graph-resources`),
  studentGraph: (courseId: string, graphId: string) =>
    request<KnowledgeGraph>(
      `/student/courses/${courseId}/graph-resources/${graphId}`,
    ),
  teacherGraphs: (courseId: string) =>
    request<GraphListItem[]>(`/teacher/courses/${courseId}/graphs`),
  teacherGraph: (graphId: string) =>
    request<KnowledgeGraph>(`/teacher/graphs/${graphId}`),
  createGraph: (courseId: string, title: string) =>
    request<KnowledgeGraph>(`/teacher/courses/${courseId}/graphs`, {
      method: "POST",
      body: JSON.stringify({ title }),
    }),
  renameGraph: (graphId: string, title: string) =>
    request<KnowledgeGraph>(`/teacher/graphs/${graphId}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),
  discardGraphDraft: (graphId: string, version: number) =>
    request<KnowledgeGraph>(
      `/teacher/graphs/${graphId}/draft?expected_revision_version=${version}`,
      { method: "DELETE" },
    ),
  deleteGraph: (graphId: string, version: number) =>
    request<void>(
      `/teacher/graphs/${graphId}?expected_revision_version=${version}`,
      { method: "DELETE" },
    ),
  createGraphRevision: (graphId: string) =>
    request<KnowledgeGraph>(`/teacher/graphs/${graphId}/revisions`, {
      method: "POST",
    }),
  validateGraph: (graphId: string, version: number) =>
    request<KnowledgeGraph>(`/teacher/graphs/${graphId}:validate`, {
      method: "POST",
      body: JSON.stringify({ expected_revision_version: version }),
    }),
  publishGraph: (graphId: string, version: number) =>
    request<KnowledgeGraph>(`/teacher/graphs/${graphId}:publish`, {
      method: "POST",
      body: JSON.stringify({ expected_revision_version: version }),
    }),
  addGraphNode: (graphId: string, payload: Record<string, unknown>) =>
    request<KnowledgeGraph>(`/teacher/graphs/${graphId}/nodes`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateGraphNode: (
    graphId: string,
    nodeId: string,
    payload: Record<string, unknown>,
  ) =>
    request<KnowledgeGraph>(`/teacher/graphs/${graphId}/nodes/${nodeId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  deleteGraphNode: (graphId: string, nodeId: string, version: number) =>
    request<KnowledgeGraph>(
      `/teacher/graphs/${graphId}/nodes/${nodeId}?expected_revision_version=${version}`,
      { method: "DELETE" },
    ),
  addGraphEdge: (graphId: string, payload: Record<string, unknown>) =>
    request<KnowledgeGraph>(`/teacher/graphs/${graphId}/edges`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateGraphEdge: (
    graphId: string,
    edgeId: string,
    payload: Record<string, unknown>,
  ) =>
    request<KnowledgeGraph>(`/teacher/graphs/${graphId}/edges/${edgeId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  deleteGraphEdge: (graphId: string, edgeId: string, version: number) =>
    request<KnowledgeGraph>(
      `/teacher/graphs/${graphId}/edges/${edgeId}?expected_revision_version=${version}`,
      { method: "DELETE" },
    ),
  graphEvidence: (
    graphId: string,
    targetType: "node" | "edge",
    targetId: string,
  ) =>
    request<GraphEvidenceBundle>(
      `/teacher/graphs/${graphId}/evidence/${targetType}/${targetId}`,
    ),
  prepareAsset: (courseId: string, file: File, purpose: AssetPurpose) =>
    request<{
      asset: SourceAsset;
      upload_url: string;
      upload_method: "PUT";
      max_bytes: number;
    }>(`/teacher/courses/${courseId}/assets:prepare-upload`, {
      method: "POST",
      body: JSON.stringify({
        filename: file.name,
        byte_size: file.size,
        declared_mime: uploadMime(file),
        purpose,
      }),
    }),
  uploadAssetContent: (uploadUrl: string, file: File) =>
    request<SourceAsset>(uploadUrl, {
      method: "PUT",
      headers: { "Content-Type": uploadMime(file) },
      body: file,
    }),
  completeAsset: (courseId: string, assetId: string) =>
    request<{ asset: SourceAsset; document: ParsedDocument }>(
      `/teacher/courses/${courseId}/assets/${assetId}:complete`,
      { method: "POST" },
    ),
  async uploadTutorAttachment(courseId: string, file: File) {
    const prepared = await request<{
      asset: SourceAsset;
      upload_url: string;
      upload_method: "PUT";
      max_bytes: number;
    }>(`/student/courses/${courseId}/tutor-attachments:prepare-upload`, {
      method: "POST",
      body: JSON.stringify({
        filename: file.name,
        byte_size: file.size,
        declared_mime: uploadMime(file),
        purpose: "tutor_attachment",
      }),
    });
    await request<SourceAsset>(prepared.upload_url, {
      method: "PUT",
      headers: { "Content-Type": uploadMime(file) },
      body: file,
    });
    const completed = await request<{
      asset: SourceAsset;
      document: ParsedDocument;
    }>(
      `/student/courses/${courseId}/tutor-attachments/${prepared.asset.id}:complete`,
      { method: "POST" },
    );
    return completed.asset;
  },
  createAlignmentRun: (
    courseId: string,
    payload: {
      source_asset_id?: string;
      manual_text?: string;
      purpose: AssetPurpose;
    },
  ) =>
    request<AlignmentRun>(`/teacher/courses/${courseId}/alignment-runs`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  decideAlignment: (
    reviewId: string,
    payload: {
      decision: "matched" | "created" | "abstained";
      selected_concept_id?: string;
      new_concept_name?: string;
      note?: string;
    },
  ) =>
    request<AlignmentRun>(`/teacher/alignment-reviews/${reviewId}:decide`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  applyAlignment: (graphId: string, runId: string, version: number) =>
    request<KnowledgeGraph>(
      `/teacher/graphs/${graphId}/alignment-runs/${runId}:apply`,
      {
        method: "POST",
        body: JSON.stringify({ expected_revision_version: version }),
      },
    ),
  modelProfiles: (taskKind: string) =>
    request<ModelProfile[]>(
      `/model-profiles?task_kind=${encodeURIComponent(taskKind)}`,
    ),
  extractGraphCandidates: (
    graphId: string,
    payload: {
      alignment_run_id: string;
      requested_profile_id: string;
      idempotency_key: string;
      expected_revision_version: number;
    },
  ) =>
    request<GraphExtractionArtifact>(
      `/teacher/graphs/${graphId}/extract-candidates`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  decideGraphExtraction: (
    artifactId: string,
    proposalId: string,
    payload: {
      decision: "accepted" | "rejected";
      expected_artifact_version: number;
      note?: string;
    },
  ) =>
    request<GraphExtractionArtifact>(
      `/teacher/graph-extractions/${artifactId}/proposals/${proposalId}`,
      { method: "PATCH", body: JSON.stringify(payload) },
    ),
  applyGraphExtraction: (
    artifactId: string,
    artifactVersion: number,
    revisionVersion: number,
  ) =>
    request<GraphExtractionArtifact>(
      `/teacher/graph-extractions/${artifactId}:apply`,
      {
        method: "POST",
        body: JSON.stringify({
          expected_artifact_version: artifactVersion,
          expected_revision_version: revisionVersion,
        }),
      },
    ),
  createGraphSemanticReview: (
    graphId: string,
    payload: {
      requested_profile_id: string;
      idempotency_key: string;
      expected_revision_version: number;
    },
  ) =>
    request<GraphSemanticReviewArtifact>(
      `/teacher/graphs/${graphId}/semantic-review`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  graphSemanticReview: (artifactId: string) =>
    request<GraphSemanticReviewArtifact>(
      `/teacher/graph-semantic-reviews/${artifactId}`,
    ),
  decideGraphSemanticReview: (
    artifactId: string,
    issueId: string,
    payload: {
      decision: "confirmed" | "ignored";
      expected_artifact_version: number;
      note?: string;
    },
  ) =>
    request<GraphSemanticReviewArtifact>(
      `/teacher/graph-semantic-reviews/${artifactId}/issues/${issueId}`,
      { method: "PATCH", body: JSON.stringify(payload) },
    ),
  videoSearchSources: (courseId: string) =>
    request<VideoSearchSources>(
      `/teacher/courses/${courseId}/video-search-sources`,
    ),
  createVideoSearch: (
    courseId: string,
    payload: Record<string, unknown>,
    idempotencyKey: string,
  ) =>
    request<VideoSearchJob>(`/courses/${courseId}/video-search-jobs`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify(payload),
    }),
  videoSearchJob: (jobId: string) =>
    request<VideoSearchJob>(`/video-search-jobs/${jobId}`),
  videoCandidates: (
    jobId: string,
    filters: {
      minDuration?: number;
      maxDuration?: number;
      contentKind?: string;
    } = {},
  ) => {
    const query = new URLSearchParams();
    if (filters.minDuration != null)
      query.set("min_duration", String(filters.minDuration));
    if (filters.maxDuration != null)
      query.set("max_duration", String(filters.maxDuration));
    if (filters.contentKind) query.set("content_kind", filters.contentKind);
    return request<VideoCandidate[]>(
      `/video-search-jobs/${jobId}/candidates${query.size ? `?${query}` : ""}`,
    );
  },
  previewVideoCandidate: (
    candidateId: string,
    action: "embedded_preview" | "original_page_opened",
    idempotencyKey: string,
  ) =>
    request(`/video-candidates/${candidateId}/preview-events`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({ action }),
    }),
  recheckVideoCandidate: (candidateId: string, idempotencyKey: string) =>
    request(`/video-candidates/${candidateId}/recheck`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
    }),
  publishVideoCandidate: (
    candidateId: string,
    audience: Record<string, unknown>,
    idempotencyKey: string,
  ) =>
    request<VideoPublication>("/video-publications", {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({
        candidate_id: candidateId,
        audience,
        intervention_plan_id: null,
      }),
    }),
  studentVideoResources: (courseId: string) =>
    request<VideoPublication[]>(`/courses/${courseId}/resources?type=video`),
  videoProgress: (publicationId: string) =>
    request<Record<string, unknown>>(
      `/video-publications/${publicationId}/progress`,
    ),
  recordVideoEvent: (
    publicationId: string,
    payload: Record<string, unknown>,
    idempotencyKey: string,
  ) =>
    request(`/video-publications/${publicationId}/events`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify(payload),
    }),
  tutorConversations: (courseId: string, q = "") =>
    request<TutorConversationItem[]>(
      `/student/courses/${courseId}/tutor/conversations${q ? `?q=${encodeURIComponent(q)}` : ""}`,
    ),
  tutorConversation: (courseId: string, conversationId: string) =>
    request<TutorConversation>(
      `/student/courses/${courseId}/tutor/conversations/${conversationId}`,
    ),
  createTutorConversation: (
    courseId: string,
    payload: {
      title?: string;
      selected_mode: TutorMode;
      requested_profile_id: string;
      experience_mode: "manual" | "automatic";
    },
  ) =>
    request<TutorConversation>(
      `/student/courses/${courseId}/tutor/conversations`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  renameTutorConversation: (
    courseId: string,
    conversationId: string,
    title: string,
    version: number,
  ) =>
    request<TutorConversation>(
      `/student/courses/${courseId}/tutor/conversations/${conversationId}`,
      { method: "PATCH", body: JSON.stringify({ title, version }) },
    ),
  deleteTutorConversation: (courseId: string, conversationId: string) =>
    request<void>(
      `/student/courses/${courseId}/tutor/conversations/${conversationId}`,
      { method: "DELETE" },
    ),
  sendTutorTurn: (
    courseId: string,
    conversationId: string,
    payload: Record<string, unknown>,
  ) =>
    request<TutorTurn>(
      `/student/courses/${courseId}/tutor/conversations/${conversationId}/turns`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  tutorMemories: (courseId: string) =>
    request<TutorMemory[]>(`/student/courses/${courseId}/tutor/memories`),
  resolveTutorMemory: (
    courseId: string,
    memoryId: string,
    payload: Record<string, unknown>,
  ) =>
    request<TutorMemory>(
      `/student/courses/${courseId}/tutor/memories/${memoryId}:resolve`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  tutorExperiences: (courseId: string) =>
    request<TutorExperience[]>(
      `/student/courses/${courseId}/tutor/experiences`,
    ),
  generateTutorExperience: (
    courseId: string,
    conversationId: string,
    payload: Record<string, unknown>,
  ) =>
    request<{ decision: string; experience: TutorExperience | null }>(
      `/student/courses/${courseId}/tutor/conversations/${conversationId}/experiences:generate`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  compressTutorMemories: (courseId: string) =>
    request<TutorMemory[]>(
      `/student/courses/${courseId}/tutor/memories:compress`,
      { method: "POST" },
    ),
  deleteTutorExperience: (courseId: string, experienceId: string) =>
    request<void>(
      `/student/courses/${courseId}/tutor/experiences/${experienceId}`,
      { method: "DELETE" },
    ),
  decisionOverview: (courseId: string) =>
    request<DecisionSnapshot>(`/courses/${courseId}/teacher/overview`),
  refreshDecisionSnapshot: (courseId: string) =>
    request<DecisionSnapshot>(
      `/courses/${courseId}/decision-snapshots:refresh`,
      { method: "POST", body: JSON.stringify({ as_of: null }) },
    ),
  courseStudents: (
    courseId: string,
    sort: "score_desc" | "score_asc" | "name" = "score_desc",
    q = "",
  ) =>
    request<StudentAttentionList>(
      `/courses/${courseId}/students?sort=${sort}&q=${encodeURIComponent(q)}&page_size=100`,
    ),
  studentLearningState: (courseId: string, studentId: string) =>
    request<StudentLearningState>(
      `/courses/${courseId}/students/${studentId}/learning-state`,
    ),
  previewAudience: (
    courseId: string,
    resourceId: string,
    payload: Record<string, unknown>,
  ) =>
    request<AudienceDraft>(
      `/teacher/courses/${courseId}/resources/${resourceId}/audience-drafts`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  getAudienceDraft: (draftId: string) =>
    request<AudienceDraft>(`/audience-drafts/${draftId}`),
  publishAudience: (
    draftId: string,
    version: number,
    acknowledgeWarnings: boolean,
    idempotencyKey: string,
  ) =>
    request<AudiencePublication>(`/audience-drafts/${draftId}/publications`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({
        draft_version: version,
        acknowledge_warnings: acknowledgeWarnings,
      }),
    }),
  getAudiencePublication: (publicationId: string) =>
    request<AudiencePublication>(`/publications/${publicationId}`),
  withdrawAudience: (publicationId: string) =>
    request<AudiencePublication>(`/publications/${publicationId}:withdraw`, {
      method: "POST",
    }),
  resourceInbox: (courseId: string) =>
    request<ResourceInboxItem[]>(`/student/courses/${courseId}/resource-inbox`),
  openInboxResource: (exposureId: string, idempotencyKey: string) =>
    request<ResourceInboxItem>(`/student/resource-inbox/${exposureId}:open`, {
      method: "POST",
      body: JSON.stringify({
        idempotency_key: idempotencyKey,
        occurred_at: new Date().toISOString(),
      }),
    }),
  completeInboxResource: (exposureId: string, idempotencyKey: string) =>
    request<ResourceInboxItem>(
      `/student/resource-inbox/${exposureId}:complete`,
      {
        method: "POST",
        body: JSON.stringify({
          idempotency_key: idempotencyKey,
          occurred_at: new Date().toISOString(),
        }),
      },
    ),
  personalizedResourceJob: (
    courseId: string,
    studentId: string,
    payload: Record<string, unknown>,
  ) =>
    request<PersonalizedResourceJob>(
      `/courses/${courseId}/students/${studentId}/personalized-resource-jobs`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  getPersonalizedResourceJob: (jobId: string) =>
    request<PersonalizedResourceJob>(`/personalized-resource-jobs/${jobId}`),
  hasToken: () => Boolean(token()),
  clearToken: () => window.sessionStorage.removeItem(TOKEN_KEY),
};
