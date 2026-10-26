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
export declare class ApiError extends Error {
  status: number;
  code: string | null;
  constructor(status: number, message: string, code?: string | null);
}
export declare const api: {
  login(
    account: string,
    password: string,
    role: Role,
  ): Promise<{
    access_token: string;
    expires_at: string;
    user: User;
  }>;
  logout(): Promise<void>;
  me: () => Promise<User>;
  courses: () => Promise<Course[]>;
  studentSummary: () => Promise<CrossCourseSummary>;
  studentOverview: (courseId: string) => Promise<StudentCourseOverview>;
  recordLearningEvent: (
    courseId: string,
    payload: Record<string, unknown>,
  ) => Promise<Record<string, unknown>>;
  teacherOverview: (courseId: string) => Promise<TeacherCourseOverview>;
  studentQuestionSets: (courseId: string) => Promise<QuestionSetList>;
  teacherQuestionSets: (courseId: string) => Promise<QuestionSetList>;
  questionSet: (setId: string) => Promise<QuestionSetDetail>;
  compilePracticeBlueprint: (
    courseId: string,
    payload: CompilePracticeBlueprintPayload,
  ) => Promise<PracticeBlueprint>;
  generateQuestionSet: (
    courseId: string,
    payload: GenerateQuestionSetPayload,
  ) => Promise<QuestionSetDetail>;
  updateTeacherQuestion: (
    questionId: string,
    payload: UpdateQuestionPayload,
  ) => Promise<QuestionSetDetail>;
  validateQuestionSet: (
    setId: string,
    version: number,
  ) => Promise<QuestionSetDetail>;
  publishQuestionSet: (
    setId: string,
    version: number,
  ) => Promise<QuestionSetDetail>;
  revealQuestionHint: (
    questionId: string,
    level: number,
    idempotencyKey: string,
  ) => Promise<RevealedHint>;
  submitQuestionAttempt: (
    questionId: string,
    payload: {
      idempotency_key: string;
      answer: Record<string, unknown>;
      expected_revision_id: string;
    },
  ) => Promise<PracticeAttemptResult>;
  questionSetProgress: (setId: string) => Promise<QuestionSetProgress>;
  attemptScore: (attemptId: string) => Promise<PracticeScore>;
  studentGraphs: (courseId: string) => Promise<GraphListItem[]>;
  studentGraph: (courseId: string, graphId: string) => Promise<KnowledgeGraph>;
  teacherGraphs: (courseId: string) => Promise<GraphListItem[]>;
  teacherGraph: (graphId: string) => Promise<KnowledgeGraph>;
  createGraph: (courseId: string, title: string) => Promise<KnowledgeGraph>;
  renameGraph: (graphId: string, title: string) => Promise<KnowledgeGraph>;
  discardGraphDraft: (
    graphId: string,
    version: number,
  ) => Promise<KnowledgeGraph>;
  deleteGraph: (graphId: string, version: number) => Promise<void>;
  createGraphRevision: (graphId: string) => Promise<KnowledgeGraph>;
  validateGraph: (graphId: string, version: number) => Promise<KnowledgeGraph>;
  publishGraph: (graphId: string, version: number) => Promise<KnowledgeGraph>;
  addGraphNode: (
    graphId: string,
    payload: Record<string, unknown>,
  ) => Promise<KnowledgeGraph>;
  updateGraphNode: (
    graphId: string,
    nodeId: string,
    payload: Record<string, unknown>,
  ) => Promise<KnowledgeGraph>;
  deleteGraphNode: (
    graphId: string,
    nodeId: string,
    version: number,
  ) => Promise<KnowledgeGraph>;
  addGraphEdge: (
    graphId: string,
    payload: Record<string, unknown>,
  ) => Promise<KnowledgeGraph>;
  updateGraphEdge: (
    graphId: string,
    edgeId: string,
    payload: Record<string, unknown>,
  ) => Promise<KnowledgeGraph>;
  deleteGraphEdge: (
    graphId: string,
    edgeId: string,
    version: number,
  ) => Promise<KnowledgeGraph>;
  graphEvidence: (
    graphId: string,
    targetType: "node" | "edge",
    targetId: string,
  ) => Promise<GraphEvidenceBundle>;
  prepareAsset: (
    courseId: string,
    file: File,
    purpose: AssetPurpose,
  ) => Promise<{
    asset: SourceAsset;
    upload_url: string;
    upload_method: "PUT";
    max_bytes: number;
  }>;
  uploadAssetContent: (uploadUrl: string, file: File) => Promise<SourceAsset>;
  completeAsset: (
    courseId: string,
    assetId: string,
  ) => Promise<{
    asset: SourceAsset;
    document: ParsedDocument;
  }>;
  uploadTutorAttachment(courseId: string, file: File): Promise<SourceAsset>;
  createAlignmentRun: (
    courseId: string,
    payload: {
      source_asset_id?: string;
      manual_text?: string;
      purpose: AssetPurpose;
    },
  ) => Promise<AlignmentRun>;
  decideAlignment: (
    reviewId: string,
    payload: {
      decision: "matched" | "created" | "abstained";
      selected_concept_id?: string;
      new_concept_name?: string;
      note?: string;
    },
  ) => Promise<AlignmentRun>;
  applyAlignment: (
    graphId: string,
    runId: string,
    version: number,
  ) => Promise<KnowledgeGraph>;
  modelProfiles: (taskKind: string) => Promise<ModelProfile[]>;
  extractGraphCandidates: (
    graphId: string,
    payload: {
      alignment_run_id: string;
      requested_profile_id: string;
      idempotency_key: string;
      expected_revision_version: number;
    },
  ) => Promise<GraphExtractionArtifact>;
  decideGraphExtraction: (
    artifactId: string,
    proposalId: string,
    payload: {
      decision: "accepted" | "rejected";
      expected_artifact_version: number;
      note?: string;
    },
  ) => Promise<GraphExtractionArtifact>;
  applyGraphExtraction: (
    artifactId: string,
    artifactVersion: number,
    revisionVersion: number,
  ) => Promise<GraphExtractionArtifact>;
  createGraphSemanticReview: (
    graphId: string,
    payload: {
      requested_profile_id: string;
      idempotency_key: string;
      expected_revision_version: number;
    },
  ) => Promise<GraphSemanticReviewArtifact>;
  graphSemanticReview: (
    artifactId: string,
  ) => Promise<GraphSemanticReviewArtifact>;
  decideGraphSemanticReview: (
    artifactId: string,
    issueId: string,
    payload: {
      decision: "confirmed" | "ignored";
      expected_artifact_version: number;
      note?: string;
    },
  ) => Promise<GraphSemanticReviewArtifact>;
  videoSearchSources: (courseId: string) => Promise<VideoSearchSources>;
  createVideoSearch: (
    courseId: string,
    payload: Record<string, unknown>,
    idempotencyKey: string,
  ) => Promise<VideoSearchJob>;
  videoSearchJob: (jobId: string) => Promise<VideoSearchJob>;
  videoCandidates: (
    jobId: string,
    filters?: {
      minDuration?: number;
      maxDuration?: number;
      contentKind?: string;
    },
  ) => Promise<VideoCandidate[]>;
  previewVideoCandidate: (
    candidateId: string,
    action: "embedded_preview" | "original_page_opened",
    idempotencyKey: string,
  ) => Promise<unknown>;
  recheckVideoCandidate: (
    candidateId: string,
    idempotencyKey: string,
  ) => Promise<unknown>;
  publishVideoCandidate: (
    candidateId: string,
    audience: Record<string, unknown>,
    idempotencyKey: string,
  ) => Promise<VideoPublication>;
  studentVideoResources: (courseId: string) => Promise<VideoPublication[]>;
  videoProgress: (publicationId: string) => Promise<Record<string, unknown>>;
  recordVideoEvent: (
    publicationId: string,
    payload: Record<string, unknown>,
    idempotencyKey: string,
  ) => Promise<unknown>;
  tutorConversations: (
    courseId: string,
    q?: string,
  ) => Promise<TutorConversationItem[]>;
  tutorConversation: (
    courseId: string,
    conversationId: string,
  ) => Promise<TutorConversation>;
  createTutorConversation: (
    courseId: string,
    payload: {
      title?: string;
      selected_mode: TutorMode;
      requested_profile_id: string;
      experience_mode: "manual" | "automatic";
    },
  ) => Promise<TutorConversation>;
  renameTutorConversation: (
    courseId: string,
    conversationId: string,
    title: string,
    version: number,
  ) => Promise<TutorConversation>;
  deleteTutorConversation: (
    courseId: string,
    conversationId: string,
  ) => Promise<void>;
  sendTutorTurn: (
    courseId: string,
    conversationId: string,
    payload: Record<string, unknown>,
  ) => Promise<TutorTurn>;
  tutorMemories: (courseId: string) => Promise<TutorMemory[]>;
  resolveTutorMemory: (
    courseId: string,
    memoryId: string,
    payload: Record<string, unknown>,
  ) => Promise<TutorMemory>;
  tutorExperiences: (courseId: string) => Promise<TutorExperience[]>;
  generateTutorExperience: (
    courseId: string,
    conversationId: string,
    payload: Record<string, unknown>,
  ) => Promise<{
    decision: string;
    experience: TutorExperience | null;
  }>;
  compressTutorMemories: (courseId: string) => Promise<TutorMemory[]>;
  deleteTutorExperience: (
    courseId: string,
    experienceId: string,
  ) => Promise<void>;
  decisionOverview: (courseId: string) => Promise<DecisionSnapshot>;
  refreshDecisionSnapshot: (courseId: string) => Promise<DecisionSnapshot>;
  courseStudents: (
    courseId: string,
    sort?: "score_desc" | "score_asc" | "name",
    q?: string,
  ) => Promise<StudentAttentionList>;
  studentLearningState: (
    courseId: string,
    studentId: string,
  ) => Promise<StudentLearningState>;
  previewAudience: (
    courseId: string,
    resourceId: string,
    payload: Record<string, unknown>,
  ) => Promise<AudienceDraft>;
  getAudienceDraft: (draftId: string) => Promise<AudienceDraft>;
  publishAudience: (
    draftId: string,
    version: number,
    acknowledgeWarnings: boolean,
    idempotencyKey: string,
  ) => Promise<AudiencePublication>;
  getAudiencePublication: (
    publicationId: string,
  ) => Promise<AudiencePublication>;
  withdrawAudience: (publicationId: string) => Promise<AudiencePublication>;
  resourceInbox: (courseId: string) => Promise<ResourceInboxItem[]>;
  openInboxResource: (
    exposureId: string,
    idempotencyKey: string,
  ) => Promise<ResourceInboxItem>;
  completeInboxResource: (
    exposureId: string,
    idempotencyKey: string,
  ) => Promise<ResourceInboxItem>;
  personalizedResourceJob: (
    courseId: string,
    studentId: string,
    payload: Record<string, unknown>,
  ) => Promise<PersonalizedResourceJob>;
  getPersonalizedResourceJob: (
    jobId: string,
  ) => Promise<PersonalizedResourceJob>;
  hasToken: () => boolean;
  clearToken: () => void;
};

export type PlatformApi = typeof api;
