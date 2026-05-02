// Shared TypeScript types mirroring the imga-api OpenAPI surface.
//
// We hand-write these (instead of generating from OpenAPI) so that
// the surface stays explicit and easy to grep. When backend response
// shapes change (Sprint 7.5.5 / Grup B), update here in one place.

export type UserTenantRole = "tenant_admin" | "analyst" | "viewer";

export type TicketState =
  | "open"
  | "in_progress"
  | "pending_customer"
  | "resolved"
  | "closed"
  | "cancelled";

export type TicketPriority = "low" | "normal" | "high" | "urgent";

export type CancellationReason = "false_positive" | "duplicate" | "spam" | "off_topic" | "other";

export type AutomationMode = "manual" | "semi_auto" | "full_auto";

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: "Bearer";
}

export interface UserSummary {
  id: string;
  email: string;
  full_name: string;
  is_super_admin: boolean;
}

export interface ActiveContext {
  tenant_id: string | null;
  tenant_name: string | null;
  tenant_slug: string | null;
  role: UserTenantRole | null;
}

export interface TenantSummary {
  id: string;
  name: string;
  slug: string;
  role: UserTenantRole;
}

export interface MeResponse {
  user: UserSummary;
  active_context: ActiveContext;
  available_tenants: TenantSummary[];
}

export interface ApiErrorBody {
  detail: string;
}

// --- Tickets (mirrors imga-api routes/tickets.py:TicketResponse) -----

export interface Ticket {
  id: string;
  tenant_id: string;
  review_id: string | null;
  category_id: string;
  state: TicketState;
  priority: TicketPriority;
  title: string;
  summary: string | null;
  assigned_to_user_id: string | null;
  created_by_user_id: string | null;
  cancellation_reason: CancellationReason | null;
  parent_ticket_id: string | null;
  opened_at: string;
  claimed_at: string | null;
  pending_since: string | null;
  resolved_at: string | null;
  closed_at: string | null;
  cancelled_at: string | null;
  customer_inbound_received_at: string | null;
  last_state_change_at: string;
}

export interface TicketListResponse {
  tickets: Ticket[];
  total: number;
  limit: number;
  offset: number;
}

// --- Backend filter surface for GET /tickets and /tickets/stats ------
// Mirrors imga_api.services.ticket_filters.TicketFilters. CSV-shaped
// fields are arrays here; the query-string builder joins them.

export type TicketSortField = "opened_at" | "last_state_change_at" | "priority";
export type SortDirection = "asc" | "desc";

/** "me" / "unassigned" are resolved server-side. UUID for a specific
 * user (Sprint 7.7.2 assignee dropdown will pass this). */
export type AssigneeFilterValue = "me" | "unassigned" | string;

export interface TicketBackendFilters {
  states?: ReadonlyArray<TicketState>;
  priorities?: ReadonlyArray<TicketPriority>;
  category_ids?: ReadonlyArray<string>;
  opened_after?: string;       // ISO 8601
  opened_before?: string;      // ISO 8601
  assignee?: AssigneeFilterValue;
  search?: string;
  order_by?: TicketSortField;
  order?: SortDirection;
  limit?: number;
  offset?: number;
}

// --- Stats (mirrors routes/tickets.py:StatsResponse) -----------------

export type TicketStatsGroupBy = "state" | "priority" | "category" | "assignee";

export interface StatsBucket {
  key: string;
  label: string;
  count: number;
}

export interface TicketStatsResponse {
  group_by: string;
  total: number;
  results: StatsBucket[];
}

// --- Ticket comments (mirrors routes/tickets.py:CommentView) ---------

export type TicketCommentKind = "internal_note" | "customer_reply";

export interface TicketComment {
  id: string;
  ticket_id: string;
  author_user_id: string | null;
  body: string;
  kind: TicketCommentKind;
  created_at: string;
  is_archived: boolean;
  archived_at: string | null;
  archived_by_user_id: string | null;
}

export interface TicketCommentsResponse {
  comments: TicketComment[];
}

// --- Polymorphic timeline (mirrors routes/tickets.py:TimelineEvent) ---

export type TimelineEventType =
  | "state_transition"
  | "comment"
  | "assignment_changed";

export interface TimelineEvent {
  type: TimelineEventType;
  id: string;
  occurred_at: string;
  actor_user_id: string | null;
  // state_transition fields
  from_state?: TicketState | null;
  to_state?: TicketState | null;
  reason?: string | null;
  // comment fields
  body?: string | null;
  kind?: TicketCommentKind | null;
  is_archived?: boolean | null;
  archived_at?: string | null;
  archived_by_user_id?: string | null;
  // assignment_changed fields (Sprint 7.7.2 patch). Either side may
  // be null (was/became unassigned), but never both.
  from_user_id?: string | null;
  to_user_id?: string | null;
}

export interface TimelineResponse {
  events: TimelineEvent[];
}

// --- Admin tenant CRUD (mirrors routes/admin/tenants.py) -------------

export type TenantPlanTier = "trial" | "starter" | "business" | "enterprise";

export interface AdminTenantSummary {
  id: string;
  name: string;
  slug: string;
  plan_tier: TenantPlanTier;
  automation_mode: AutomationMode;
  created_at: string;
  deleted_at: string | null;
}

export interface AdminTenantListResponse {
  tenants: AdminTenantSummary[];
}

export interface AdminTenantCreateRequest {
  name: string;
  slug: string;
  plan_tier?: TenantPlanTier;
  automation_mode?: AutomationMode;
  initial_admin?: {
    email: string;
    full_name: string;
  };
}

export interface AdminTenantCreateResponse {
  tenant: AdminTenantSummary;
  /** Plaintext invitation token, returned exactly once when
   * `initial_admin` was set. Show then forget. */
  initial_invitation_token: string | null;
}

export interface AdminTenantUpdateRequest {
  name?: string;
  plan_tier?: TenantPlanTier;
  automation_mode?: AutomationMode;
}

// --- Admin invitation create (mirrors routes/admin/invitations.py) ---

export interface AdminInvitationCreateRequest {
  email: string;
  role: UserTenantRole;
}

export interface AdminInvitationCreateResponse {
  invitation_id: string;
  token: string;
  email: string;
  role: string;
  expires_at: string;
}

// --- Invitation flow (mirrors routes/invitations.py) -----------------

export interface InvitationPreview {
  tenant_id: string;
  tenant_name: string;
  invited_email: string;
  role: UserTenantRole;
  expires_at: string;
  /** Sprint 7.5.5 amendment — true when the invited email already
   * belongs to a registered user. The frontend uses this to choose
   * between the new-account and re-auth forms. */
  email_exists: boolean;
}

export interface AcceptInvitationNewRequest {
  full_name: string;
  password: string;
}

export interface AcceptInvitationExistingRequest {
  password: string;
}

export type InvitationAcceptResponse = TokenPair;

// --- /tenants/me/analyze (mirrors routes/tenant_analyze.py) -----------

export type ReviewDecision =
  | "create"
  | "skipped_belirsiz"
  | "skipped_mode"
  | "skipped_threshold"
  | "skipped_dedup";

export interface AnalysisResult {
  text: string;
  sentiment_label: "POZITIF" | "NEGATIF" | "NÖTR";
  sentiment_score: number;
  summary: string | null;
  customer_perspective: string | null;
  company_perspective: string | null;
  risk_class: "POZITIF" | "NEGATIF" | "NÖTR" | null;
  sla_detected: string | null;
  categorization: {
    primary: string;
    primary_confidence: number;
    requires_manual_review: boolean;
  } | null;
  overrides_applied: OverrideHit[];
}

export interface TenantAnalyzeResponse {
  review_id: string;
  decision: ReviewDecision;
  decision_reason: string | null;
  ticket_id: string | null;
  analyzed_at: string;
  analysis: AnalysisResult;
}

// --- Tenant directory (mirrors routes/tenant_directory.py:TenantMemberView) -

export interface TenantMember {
  user_id: string;
  email: string;
  full_name: string;
  role: UserTenantRole;
  is_active: boolean;
  last_login_at: string | null;
  invitation_accepted_at: string | null;
}

export interface TenantMembersResponse {
  members: TenantMember[];
}

// --- Tenant categories (mirrors routes/tenant_config.py:CategoryView) -

export interface CategoryView {
  id: string;
  code: string;
  label_tr: string;
  label_en: string | null;
  description: string | null;
  is_global: boolean;
  is_enabled: boolean;
  is_archived: boolean;
}

export interface CategoriesResponse {
  categories: CategoryView[];
}

// ---------------------------------------------------------------------------
// Sprint 8.3.1 — batch upload + reviews list
// ---------------------------------------------------------------------------

export type BatchJobStatus =
  | "queued"
  | "processing"
  | "completed"
  | "failed"
  | "cancelled";

export interface BatchJob {
  job_id: string;
  status: BatchJobStatus;
  file_name: string;
  file_size_bytes: number;
  text_column: string;
  source_column: string | null;
  auto_create_tickets: boolean;
  total_rows: number;
  processed_rows: number;
  succeeded_rows: number;
  failed_rows: number;
  tickets_created: number;
  duplicates_skipped: number;
  error_summary: Array<{ row: number | null; error: string }>;
  estimated_seconds: number | null;
  triggered_by_user_id: string | null;
  started_at: string | null;
  completed_at: string | null;
  cancelled_at: string | null;
  created_at: string;
}

export interface BatchJobListResponse {
  jobs: BatchJob[];
  total: number;
}

export type ReviewSourceType = "manual" | "batch" | "api";

// Sprint 8.3.4 — five known override layer codes. Server may emit
// any one of these in `overrides_applied[].layer`; the UI maps them
// to Türkçe labels via OVERRIDE_LAYER_LABELS_TR below.
export type OverrideLayer =
  | "knowledge_base"
  | "critical"
  | "tier1"
  | "sla"
  | "tier2";

export const OVERRIDE_LAYER_LABELS_TR: Record<OverrideLayer, string> = {
  knowledge_base: "Bilgi Tabanı Kuralı",
  critical: "Kritik Anahtar Kelime",
  tier1: "Güçlü Negatif Sıfat",
  sla: "SLA Tetikleyicisi",
  tier2: "İkincil Tetikleyici",
};

export interface OverrideHit {
  layer: OverrideLayer;
  matched_keywords: string[];
  score: number;
  detail: string | null;
}

export interface ReviewListItem {
  id: string;
  text: string;
  sentiment_label: string;
  sentiment_score: number;
  primary_category: string;
  primary_confidence: number;
  decision: ReviewDecision;
  decision_reason: string | null;
  ticket_id: string | null;
  batch_job_id: string | null;
  source_type: ReviewSourceType;
  analyzed_at: string;
  submitted_by_user_id: string | null;
  override_count: number;
}

export interface ReviewListResponse {
  items: ReviewListItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface ReviewDetail {
  id: string;
  text: string;
  text_hash: string;
  analyzed_at: string;
  source_type: ReviewSourceType;
  batch_job_id: string | null;
  sentiment: {
    label: string;
    score: number;
    raw_score: number;
    final_score: number;
  };
  categorization: {
    primary: string;
    primary_confidence: number;
  };
  overrides_applied: OverrideHit[];
  ticket_id: string | null;
  auto_ticket_decision: ReviewDecision;
  auto_ticket_decision_reason: string | null;
}

export interface ReviewListFilters {
  date_from?: string;
  date_to?: string;
  sentiment_labels?: string[];
  has_ticket?: boolean;
  batch_job_id?: string;
  source_types?: ReviewSourceType[];
  decisions?: ReviewDecision[];
  search?: string;
  limit?: number;
  offset?: number;
  order_by?: "created_at" | "sentiment_score";
  order?: "asc" | "desc";
}

// ---------------------------------------------------------------------------
// Sprint 8.3.2 — multi-sheet Excel/CSV reports
// ---------------------------------------------------------------------------

export type ReportType = "comprehensive" | "reviews_only" | "tickets_only";
export type ReportFormat = "xlsx" | "csv";
export type ReportStatus = "queued" | "generating" | "completed" | "failed";

export interface ReportFiltersInput {
  date_from?: string;
  date_to?: string;
  category_ids?: string[];
  sentiment_labels?: string[];
  ticket_states?: string[];
  batch_job_id?: string;
}

export interface GenerateReportRequest {
  report_type: ReportType;
  format: ReportFormat;
  filters?: ReportFiltersInput;
}

export interface GenerateReportResponse {
  report_id: string;
  status: ReportStatus;
  estimated_seconds: number;
  row_count_estimate: number;
}

export interface ReportEstimateResponse {
  row_count_estimate: number;
  estimated_seconds: number;
  review_rows: number;
  ticket_rows: number;
}

export interface ReportJobView {
  report_id: string;
  status: ReportStatus;
  report_type: ReportType;
  format: ReportFormat;
  filters: Record<string, unknown>;
  row_count: number | null;
  file_size_bytes: number | null;
  error_message: string | null;
  triggered_by_user_id: string | null;
  started_at: string | null;
  completed_at: string | null;
  expires_at: string;
  created_at: string;
}

export interface ReportListResponse {
  reports: ReportJobView[];
  total: number;
}

// ---------------------------------------------------------------------------
// Sprint 8.3.3 — analytics endpoints
// ---------------------------------------------------------------------------

export type Granularity = "day" | "week" | "month";

export interface SentimentDistRow {
  label: string;
  count: number;
  percentage: number;
  avg_score: number;
}

export interface SentimentDistResponse {
  total: number;
  data: SentimentDistRow[];
}

export interface CategoryDistRow {
  category: string;
  category_label_tr: string;
  count: number;
  percentage: number;
}

export interface CategoryDistResponse {
  total: number;
  data: CategoryDistRow[];
}

export interface SentimentByCategoryResponse {
  categories: string[];
  category_labels_tr: string[];
  sentiments: string[];
  matrix: number[][];
  totals_by_category: number[];
  totals_by_sentiment: number[];
}

export interface OverrideStatsRow {
  layer: string;
  layer_label_tr: string;
  trigger_count: number;
  trigger_percentage: number;
  direction: string;
  avg_impact: number;
  max_impact: number;
}

export interface OverrideStatsResponse {
  total_reviews: number;
  data: OverrideStatsRow[];
}

export interface TimelinePoint {
  date: string;
  negatif: number;
  nötr: number;
  pozitif: number;
  total: number;
  avg_score: number;
}

export interface SentimentTimelineResponse {
  granularity: Granularity;
  data: TimelinePoint[];
}

export interface ResolutionBucket {
  bucket: string;
  count: number;
}

export interface ResolutionByCategory {
  category: string;
  avg_hours: number;
  count: number;
}

export interface TicketResolutionResponse {
  total_resolved_tickets: number;
  avg_resolution_hours: number;
  median_resolution_hours: number;
  p95_resolution_hours: number;
  distribution: ResolutionBucket[];
  by_category: ResolutionByCategory[];
}

export interface SensitivityBucket {
  range_start: number;
  range_end: number;
  count: number;
}

export interface SensitivityStats {
  mean: number;
  median: number;
  std_dev: number;
}

export interface SensitivityDistResponse {
  total: number;
  buckets: SensitivityBucket[];
  stats: SensitivityStats;
}

export interface AnalyticsFilters {
  date_from?: string;
  date_to?: string;
  sentiment_labels?: string[];
  category_ids?: string[];
  source_types?: string[];
  batch_job_id?: string;
}
