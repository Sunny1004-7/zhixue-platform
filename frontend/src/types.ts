export type Role = "student" | "teacher";

export type User = {
  id: string;
  email: string;
  role: Role;
  name: string;
  initials: string;
  profile_title: string;
};

export type Course = {
  id: string;
  code: string;
  title: string;
  short_title: string;
  term: string;
  accent: "indigo" | "cyan" | "amber";
  teacher: string;
  mastery: number | null;
  progress: number | null;
  weekly_minutes: number | null;
  streak_days: number | null;
  goal: string | null;
  focus: string | null;
};

export type CrossCourseSummary = {
  active_courses: number;
  weekly_minutes: number;
  pending_resources: number;
  overall_mastery: number;
  mastery_delta: number;
  strong_topics: string[];
  weak_topics: string[];
  daily_minutes: number[];
  daily_average: number;
  peak_day: string;
  streak_days: number;
  resource_completion: number;
  preferred_pattern: string;
};

export type TrendMetric = { value: number; delta: string; trend: number[] };

export type KnowledgeState = {
  concept_id: string;
  label: string;
  mastery: number;
  correct_rate: number;
  evidence_count: number;
  confidence: number;
  state: "weak" | "mastered" | "unseen";
  uncertainty: number;
  effective_evidence: number;
  trend_30d: number;
  last_evidence_at: string | null;
  top_evidence: string[];
  model_version: string;
};

export type LearningResource = {
  id: string;
  resource_type: "knowledge_graph" | "question_set" | "learning_video";
  title: string;
  detail: string;
  progress_completed: number | null;
  progress_total: number | null;
  accuracy: number | null;
};

export type LearningActivity = {
  id: string;
  title: string;
  detail: string;
  activity_type: "result" | "learn" | "practice";
  occurred_at: string;
};

export type StudentCourseOverview = {
  course: Course;
  focus_summary: string;
  mastery: TrendMetric;
  resource_completion: TrendMetric;
  recent_accuracy: TrendMetric;
  streak: TrendMetric;
  weekly_activity: number[];
  daily_average: number;
  efficient_sessions: number;
  knowledge_states: KnowledgeState[];
  recent_resources: LearningResource[];
  recent_activities: LearningActivity[];
};

export type TeacherCourseOverview = {
  course: Course;
  class_name: string;
  student_count: number;
  average_mastery: number;
  average_accuracy: number;
  resource_completion: number;
  priority_student_count: number;
};

export type GraphNode = {
  id: string;
  concept_id: string;
  label: string;
  node_type: "foundation" | "core" | "application";
  definition: string;
  key_point: string;
  misconception: string;
  origin: string;
  confidence: number;
  position_x: number;
  position_y: number;
  evidence_count: number;
  mastery: number | null;
  mastery_state: "weak" | "mastered" | "unseen" | null;
};

export type GraphEdge = {
  id: string;
  from_node_id: string;
  to_node_id: string;
  relation: "prerequisite" | "contains" | "application" | "contrast";
  origin: string;
  confidence: number;
  evidence_count: number;
};

export type GraphQuality = {
  hard_pass: boolean;
  quality_score: number;
  metrics: Record<string, number>;
  issues: Array<{
    code: string;
    message: string;
    target_id: string | null;
    severity: string;
  }>;
  validator_version: string;
  created_at: string;
};

export type GraphListItem = {
  id: string;
  course_id: string;
  title: string;
  status: "draft" | "published";
  working_revision_id: string | null;
  published_revision_id: string | null;
  revision_no: number | null;
  node_count: number;
  edge_count: number;
  updated_at: string;
};

export type KnowledgeGraph = {
  id: string;
  course_id: string;
  title: string;
  status: "draft" | "published";
  revision_id: string;
  revision_no: number;
  revision_status: "draft" | "published";
  review_status: "pending" | "passed" | "failed" | "teacher_validated";
  mode: "new" | "update" | "curated_seed";
  source_type: string;
  source_summary: string;
  version: number;
  nodes: GraphNode[];
  edges: GraphEdge[];
  quality: GraphQuality | null;
};

export type GraphEvidenceSource = {
  id: string;
  target_type: "node" | "edge";
  target_id: string;
  source_kind: "material_span" | "teacher_statement" | "curated_seed";
  evidence_span_id: string | null;
  source_name: string | null;
  quote: string | null;
  locator: Record<string, unknown> | null;
  assertion_note: string;
  confidence: number;
  source_model_run_id: string | null;
  created_at: string;
};

export type GraphEvidenceBundle = {
  graph_id: string;
  revision_id: string;
  revision_version: number;
  target_type: "node" | "edge";
  target_id: string;
  links: GraphEvidenceSource[];
};

export type AssetPurpose =
  | "graph_build"
  | "graph_update"
  | "question_generation"
  | "video_search"
  | "tutor_attachment";

export type SourceAsset = {
  id: string;
  course_id: string;
  purpose: AssetPurpose;
  original_name: string;
  extension: string;
  declared_mime: string;
  detected_mime: string | null;
  expected_size: number;
  byte_size: number | null;
  sha256: string | null;
  status: "prepared" | "uploaded" | "parsed" | "rejected" | "deleted";
  security_status: "pending" | "accepted" | "rejected" | "deleted";
  rejection_code: string | null;
  rejection_reason: string | null;
  created_at: string;
  uploaded_at: string | null;
  accepted_at: string | null;
  deleted_at: string | null;
};

export type ParsedDocument = {
  id: string;
  asset_id: string;
  parser_name: string;
  parser_version: string;
  status: "parsed" | "invalidated";
  title: string;
  segment_count: number;
  page_count: number;
  text_length: number;
  chunk_count: number;
  warnings: Array<Record<string, string>>;
  created_at: string;
};

export type AlignmentCandidate = {
  concept_id: string;
  concept_name: string;
  rank: number;
  lexical_score: number;
  context_score: number;
  graph_score: number;
  final_score: number;
  recommended: boolean;
};

export type AlignmentMention = {
  id: string;
  ordinal: number;
  raw_text: string;
  normalized_text: string;
  context: string;
  status: "matched" | "ambiguous" | "abstained";
  evidence_span_id: string | null;
  candidates: AlignmentCandidate[];
  review: {
    id: string;
    status: "pending" | "decided";
    decision: "matched" | "created" | "abstained" | null;
    selected_concept_id: string | null;
    note: string;
    decided_at: string | null;
  } | null;
};

export type AlignmentRun = {
  id: string;
  course_id: string;
  source_type: "asset" | "manual";
  source_asset_id: string | null;
  purpose: AssetPurpose;
  mode: "concept_alignment";
  status: "completed" | "needs_review" | "invalidated" | "failed";
  parser_version: string | null;
  ontology_version: string;
  aligner_version: string;
  thresholds: Record<string, number>;
  summary: Record<string, number>;
  created_at: string;
  completed_at: string | null;
  mentions: AlignmentMention[];
};

export type ModelProfile = {
  id: string;
  display_name: string;
  task_kinds: string[];
  config_revision: string;
  capabilities: string[];
  available: boolean;
  unavailable_reason: string | null;
};

export type ModelRun = {
  id: string;
  task_kind: string;
  requested_profile_id: string;
  actual_profile_id: string | null;
  provider_model_id: string | null;
  task_policy_version: string;
  prompt_template_version: string | null;
  status: string;
  fallback_reason: string | null;
  error_code: string | null;
  safe_error: string | null;
  attempt_count: number;
  usage: Record<string, number | null>;
  audit_hash: string | null;
  created_at: string;
  completed_at: string | null;
};

export type GraphExtractionProposal = {
  id: string;
  proposal_kind: "concept" | "relation";
  concept_id: string | null;
  concept_label: string | null;
  from_concept_id: string | null;
  from_label: string | null;
  to_concept_id: string | null;
  to_label: string | null;
  relation: GraphEdge["relation"] | null;
  evidence_span_ids: string[];
  confidence: number;
  rationale: string;
  status: "pending" | "accepted" | "rejected";
  review_note: string;
};

export type GraphExtractionArtifact = {
  id: string;
  course_id: string;
  graph_id: string;
  revision_id: string;
  alignment_run_id: string;
  base_revision_version: number;
  status:
    | "awaiting_review"
    | "ready_to_apply"
    | "rejected"
    | "applied"
    | "invalidated";
  version: number;
  model_run: ModelRun;
  proposals: GraphExtractionProposal[];
  created_at: string;
  applied_at: string | null;
};

export type GraphSemanticReviewIssue = {
  id: string;
  issue_code: string;
  severity: "info" | "warning" | "error";
  target_type: "graph" | "node" | "edge";
  target_id: string;
  target_label: string | null;
  evidence_span_ids: string[];
  claim: string;
  suggestion: string;
  confidence: number;
  status: "pending" | "confirmed" | "ignored";
  review_note: string;
};

export type GraphSemanticReviewArtifact = {
  id: string;
  course_id: string;
  graph_id: string;
  revision_id: string;
  base_revision_version: number;
  independence_status: string;
  status:
    | "awaiting_review"
    | "reviewed"
    | "changes_required"
    | "passed"
    | "superseded";
  summary: Record<string, unknown>;
  version: number;
  model_run: ModelRun;
  issues: GraphSemanticReviewIssue[];
  created_at: string;
  completed_at: string | null;
};

export type QuestionType =
  | "single"
  | "multiple"
  | "judgment"
  | "fill"
  | "short"
  | "scenario";

export type QuestionConceptRef = {
  concept_id: string;
  label: string;
  weight?: number;
};

export type QuestionOption = {
  id: string;
  position: number;
  content: string;
  is_correct?: boolean;
};

export type PracticeScore = {
  attempt_id: string;
  score: number;
  is_correct: boolean | null;
  confidence: number;
  grading_mode: string;
  review_status: "graded" | "needs_review" | "reviewed" | string;
  feedback: Record<string, unknown>;
  graded_at: string;
};

export type QuestionAttemptState = {
  attempt_id: string | null;
  attempt_no: number;
  answer: Record<string, unknown> | null;
  hint_level: number;
  status: string;
  submitted_at: string | null;
  score: PracticeScore | null;
  revealed_hints?: RevealedHint[];
};

export type PracticeQuestion = {
  id: string;
  position: number;
  type: QuestionType;
  prompt: string;
  options: QuestionOption[];
  concepts: QuestionConceptRef[];
  hints_available: number;
  attempt_state: QuestionAttemptState | null;
  answer_spec?: Record<string, unknown>;
  rubric?: Array<Record<string, unknown>>;
  explanation?: string;
  cognitive_level?: string;
  difficulty_prior?: number;
};

export type QuestionSetSummary = {
  id: string;
  title: string;
  status: "draft" | "validated" | "published" | string;
  visibility: "private" | "course" | string;
  revision_id: string;
  revision_no: number;
  revision_version: number;
  total: number;
  completed: number;
  average_score: number | null;
  concepts: QuestionConceptRef[];
  source_kind: string;
  model_run?: ModelRun | null;
};

export type QuestionSetDetail = QuestionSetSummary & {
  course_id: string;
  quality_status: string;
  source_summary: string;
  questions: PracticeQuestion[];
};

export type QuestionSetList = {
  items: QuestionSetSummary[];
};

export type QuestionTypeCounts = Record<QuestionType, number>;

export type PracticeBlueprintConcept = {
  concept_id: string;
  counts: QuestionTypeCounts;
};

export type PracticeBlueprintCell = {
  concept_id: string;
  concept_label: string;
  question_type: QuestionType;
  count: number;
  difficulty_target: number;
  cognitive_level: string;
  position: number;
};

export type PracticeBlueprint = {
  id: string;
  version: number;
  total: number;
  cells: PracticeBlueprintCell[];
  source_summary: Record<string, unknown>;
};

export type CompilePracticeBlueprintPayload = {
  source_method: "history" | "recorded" | "graph" | "alignment";
  difficulty_mode:
    | "personalized"
    | "basic"
    | "standard"
    | "balanced"
    | "challenge";
  graph_id?: string;
  alignment_run_id?: string;
  requested_profile_id?: string;
  concepts: PracticeBlueprintConcept[];
};

export type GenerateQuestionSetPayload = {
  blueprint_id: string;
  title: string;
  requested_profile_id: string;
  idempotency_key: string;
};

export type RevealedHint = {
  question_id: string;
  level: number;
  content: string;
  revealed_at?: string;
};

export type PracticeAttempt = {
  id: string;
  question_id: string;
  question_set_id: string;
  revision_id: string;
  attempt_no: number;
  answer: Record<string, unknown>;
  hint_level: number;
  status: string;
  submitted_at: string;
};

export type PracticeAttemptResult = {
  attempt: PracticeAttempt;
  score: PracticeScore | null;
};

export type QuestionSetProgressItem = {
  question_id: string;
  position: number;
  completed: boolean;
  hint_level: number;
  attempt_id: string | null;
  score: number | null;
  review_status: string | null;
};

export type QuestionSetProgress = {
  question_set_id: string;
  revision_id: string;
  total: number;
  completed: number;
  average_score: number | null;
  items: QuestionSetProgressItem[];
};

export type UpdateQuestionPayload = {
  expected_revision_version: number;
  prompt: string;
  options: Array<{ id?: string; content: string; is_correct?: boolean }>;
  answer_spec: Record<string, unknown>;
  rubric: Array<Record<string, unknown>>;
  explanation: string;
  cognitive_level: string;
  difficulty_prior: number;
};

export type VideoSourceTopic = {
  concept_id: string;
  label: string;
  correct_rate: number | null;
  evidence_count: number;
};

export type VideoSearchSources = {
  course_id: string;
  recorded_topics: VideoSourceTopic[];
  graphs: Array<{
    graph_id: string;
    title: string;
    published_revision_id: string;
    topics: VideoSourceTopic[];
  }>;
  parsed_assets: Array<{
    asset_id: string;
    original_name: string;
    parsed_title: string;
    accepted_at: string | null;
  }>;
};

export type VideoSearchJob = {
  id: string;
  course_id: string;
  source_mode: "graph" | "records" | "files" | "manual";
  requested_profile_id: string | null;
  actual_profile_id: string | null;
  deterministic_degrade: boolean;
  status: "created" | "retrieving" | "completed" | "partial" | "failed";
  provider_statuses: Array<{
    provider: string;
    status: string;
    discovered_count: number;
    accepted_count: number;
    error_code: string | null;
    safe_message: string | null;
  }>;
  warnings: Array<Record<string, unknown>>;
  candidate_count: number;
  safe_error_code: string | null;
  safe_error_message: string | null;
  created_at: string;
  completed_at: string | null;
};

export type VideoCandidate = {
  id: string;
  job_id: string;
  provider: string;
  external_id: string;
  canonical_url: string;
  embed_url: string | null;
  title: string;
  creator: string | null;
  description: string;
  thumbnail_url: string | null;
  duration_seconds: number | null;
  content_type: string | null;
  content_kind: string;
  license_name: string | null;
  license_url: string | null;
  scores: {
    match: number;
    completeness: number;
    trust: number;
    clarity: number | null;
    final: number;
  };
  matched_topic_ids: string[];
  evidence_level: "E0" | "E1" | "E2" | "E3";
  verified_scope: string[];
  uncertainty_reason: string | null;
  verification_status: string;
  lifecycle_status: string;
  rank: number;
  verified_at: string;
  verification_expires_at: string | null;
  preview_required: boolean;
  previewed: boolean;
};

export type VideoPublication = {
  id: string;
  course_id: string;
  candidate_id: string;
  status: string;
  resource: Record<string, unknown>;
  audience: Record<string, unknown>;
  recipient_count: number;
  created_at: string;
  duplicate: boolean;
};

export type TutorMode =
  | "adaptive"
  | "coach"
  | "visualize"
  | "practice"
  | "research"
  | "explain";

export type TutorMessage = {
  id: string;
  turn_id: string | null;
  ordinal: number;
  role: "user" | "assistant";
  title: string | null;
  body: string;
  strategy: Exclude<TutorMode, "adaptive"> | null;
  checkpoint: Record<string, unknown>;
  visual: Record<string, unknown> | null;
  citations: Array<{ label?: string; url?: string; claim?: string }>;
  inline_practice: Record<string, unknown> | null;
  created_at: string;
};

export type TutorConversationItem = {
  id: string;
  course_id: string;
  title: string;
  selected_mode: TutorMode;
  requested_profile_id: string;
  experience_mode: "manual" | "automatic";
  version: number;
  preview: string;
  message_count: number;
  created_at: string;
  updated_at: string;
};

export type TutorConversation = TutorConversationItem & {
  messages: TutorMessage[];
};

export type TutorTurn = {
  turn_id: string;
  conversation_id: string;
  conversation_version: number;
  duplicate: boolean;
  model_execution: Record<string, unknown>;
  resolved_concept_ids: string[];
  strategy_plan: Record<string, unknown>;
  answer: TutorMessage;
  experience_decision: Record<string, unknown>;
  quality: Record<string, unknown>;
};

export type TutorMemory = {
  id: string;
  course_id: string;
  memory_kind: string;
  content: string;
  confidence: number;
  status: string;
  conflict_group: string | null;
  expires_at: string | null;
  created_at: string;
  updated_at: string;
  source_count: number;
};

export type TutorExperience = {
  id: string;
  course_id: string;
  title: string;
  context: string;
  method: string;
  evidence_summary: string;
  confidence: number;
  generation_mode: string;
  status: string;
  created_at: string;
  updated_at: string;
};

export type AttentionComponents = {
  practice_count: number;
  accuracy: number;
  resource_completion: number;
  effective_tutoring_count: number;
  practice_score: number;
  accuracy_score: number;
  resource_score: number;
  tutoring_score: number;
};

export type StudentAttention = {
  student_id: string;
  student_name: string;
  initials: string;
  rank: number;
  score: number;
  confidence: number;
  components: AttentionComponents;
  last_activity_at: string | null;
  priority: boolean;
};

export type DecisionSnapshot = {
  snapshot_id: string;
  course_id: string;
  as_of: string;
  snapshot_hash: string;
  student_count: number;
  aggregate: Record<string, unknown>;
  algorithm_version: string;
  priority_students: StudentAttention[];
  created_at: string;
};

export type StudentAttentionList = {
  snapshot_id: string;
  snapshot_hash: string;
  page: number;
  page_size: number;
  total: number;
  items: StudentAttention[];
};

export type StudentLearningState = {
  snapshot_id: string;
  course_id: string;
  student_id: string;
  student_name: string;
  rank: number;
  score: number;
  confidence: number;
  components: AttentionComponents;
  concepts: Array<{
    concept_id: string;
    label: string;
    state: "weak" | "mastered" | "unseen";
    mastery: number;
    accuracy: number;
    evidence_count: number;
    confidence: number;
    low_evidence: boolean;
    trend_30d: number;
    last_evidence_at: string | null;
  }>;
  weak_concept_ids: string[];
  privacy_boundary: string;
};

export type AudienceDraft = {
  id: string;
  course_id: string;
  resource: Record<string, unknown>;
  audience_mode: "class" | "concept_directed" | "single";
  selected_concept_ids: string[];
  selected_states: Array<"weak" | "mastered" | "unseen">;
  suggested_student_ids: string[];
  final_student_ids: string[];
  candidates: Array<{
    student_id: string;
    student_name: string;
    suggested: boolean;
    selected: boolean;
    override_action: string | null;
    matched_concept_ids: string[];
    matched_states: string[];
    reason_codes: string[];
    warnings: Array<Record<string, unknown>>;
  }>;
  status: string;
  snapshot_hash: string;
  version: number;
  expires_at: string;
  warnings_require_confirmation: boolean;
};

export type AudiencePublication = {
  id: string;
  draft_id: string;
  course_id: string;
  resource: Record<string, unknown>;
  audience_mode: "class" | "concept_directed" | "single";
  recipient_count: number;
  status: string;
  snapshot_hash: string;
  algorithm_version: string;
  published_at: string;
  withdrawn_at: string | null;
};

export type PersonalizedResourceJob = {
  id: string;
  student_id: string;
  course_id: string;
  resource_type: "graph" | "question_set" | "video";
  concept_ids: string[];
  upstream_job_id: string;
  upstream_status: Record<string, unknown>;
  status: string;
  created_at: string;
  updated_at: string;
};

export type ResourceInboxItem = {
  exposure_id: string;
  publication_id: string;
  course_id: string;
  resource_type: "graph" | "question_set" | "video";
  resource: Record<string, unknown>;
  personalized: boolean;
  delivery_status: string;
  delivered_at: string;
  opened_at: string | null;
  completed_at: string | null;
};
