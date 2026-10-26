export type VideoSourceMode = 'graph' | 'records' | 'files' | 'manual';

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
  source_mode: VideoSourceMode;
  requested_profile_id: string | null;
  actual_profile_id: string | null;
  deterministic_degrade: boolean;
  status: 'created' | 'retrieving' | 'completed' | 'partial' | 'failed';
  provider_statuses: Array<{
    provider: string;
    status: 'completed' | 'partial' | 'unavailable';
    discovered_count: number;
    accepted_count: number;
    error_code: string | null;
    safe_message: string | null;
  }>;
  warnings: Array<{ code?: string; message?: string }>;
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
  content_kind: 'video' | 'lecture' | 'tutorial' | 'case';
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
  evidence_level: 'E0' | 'E1' | 'E2' | 'E3';
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

export type VideoAudience = {
  mode: 'all' | 'states';
  topic_ids?: string[];
  states?: Array<'weak' | 'mastered' | 'unseen'>;
};

export type VideoPublication = {
  id: string;
  course_id: string;
  candidate_id: string;
  status: string;
  resource: {
    title: string;
    creator: string | null;
    canonical_url: string;
    embed_url: string | null;
    thumbnail_url: string | null;
    duration_seconds: number | null;
    content_kind: string;
    license_name: string | null;
    license_url: string | null;
    matched_topic_ids: string[];
    evidence_level: string;
    verified_scope: string[];
    verified_at: string;
    verification_expires_at: string;
    known_limitations: string[];
    chapters: Array<{ id: string; title: string; start_second: number }>;
  };
  audience: VideoAudience;
  recipient_count: number;
  created_at: string;
  duplicate: boolean;
};

export type VideoProgress = {
  publication_id: string;
  active_seconds: number;
  max_position_seconds: number | null;
  progress_ratio: number;
  foreground_ratio: number;
  reliability: number;
  completed: boolean;
  evidence_scope: 'verified_playback' | 'resource_interaction_only';
  last_event_at: string | null;
};

export type VideoPlayerEvent = {
  event_type: 'opened' | 'playback' | 'heartbeat' | 'chapter_opened' | 'completed' | 'feedback';
  occurred_at: string;
  player_signal: 'official_sdk' | 'heartbeat' | 'chapter' | 'page_only';
  position_seconds?: number;
  active_seconds_delta?: number;
  foreground_ratio?: number;
  chapter_id?: string;
  feedback?: 'helpful' | 'not_helpful';
};
