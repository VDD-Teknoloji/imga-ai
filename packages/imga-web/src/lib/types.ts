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
  opened_after?: string; // ISO 8601
  opened_before?: string; // ISO 8601
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

export type TimelineEventType = "state_transition" | "comment" | "assignment_changed";

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
  // Sprint 8.3.5.6 — heuristic taxonomy match. Both null when the
  // tenant's taxonomy was empty or no keyword matched. Distinct from
  // AnalysisResult.company_perspective (legacy free-text field).
  company_perspective_code: string | null;
  company_perspective_label_tr: string | null;
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

export type BatchJobStatus = "queued" | "processing" | "completed" | "failed" | "cancelled";

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
export type OverrideLayer = "knowledge_base" | "critical" | "tier1" | "sla" | "tier2";

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
  // Sprint 8.3.5.6 — heuristic match for the review. ``code`` null when
  // the heuristic didn't fire; ``label_tr`` additionally null when the
  // tenant's taxonomy row was deleted after analyze (Sprint 8.3.7).
  company_perspective_code: string | null;
  company_perspective_label_tr: string | null;
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
  // Sprint 8.3.5.6 — parallel dimension to BERT primary. Both fields
  // can be null; UI reads them together to render the perspective
  // section.
  company_perspective: {
    code: string | null;
    label_tr: string | null;
  };
  overrides_applied: OverrideHit[];
  ticket_id: string | null;
  auto_ticket_decision: ReviewDecision;
  auto_ticket_decision_reason: string | null;
  // Sprint 8.3.5 NPS — null when the upload row didn't carry an NPS.
  nps_score: number | null;
  nps_category: "detractor" | "passive" | "promoter" | null;
}

export interface ReviewListFilters {
  date_from?: string;
  date_to?: string;
  sentiment_labels?: string[];
  has_ticket?: boolean;
  batch_job_id?: string;
  source_types?: ReviewSourceType[];
  decisions?: ReviewDecision[];
  /** Sprint 8.3.5.6 — CSV of CategoryTaxonomy.code values; the literal
   * "__unmatched__" sentinel filters to rows where the heuristic didn't
   * fire (NULL company_perspective_code). Mixing it with real codes is
   * an OR. */
  perspective_codes?: string[];
  /** Sprint 8.3.10 — CSV of BERT primary_category codes. Cross-analysis
   * heatmap drill-down on /insights passes this to scope the listing
   * to the clicked cell's category. */
  primary_categories?: string[];
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

// ---------------------------------------------------------------------------
// Sprint 8.3.5 — NPS + headline metrics + company-perspective taxonomy
// ---------------------------------------------------------------------------

/** ``score`` is null when total_count == 0 — the dashboard renders a
 *  "yeterli veri yok" state instead of a misleading 0.0. */
export interface NPSSummary {
  score: number | null;
  detractor_count: number;
  passive_count: number;
  promoter_count: number;
  total_count: number;
  coverage_percent: number;
}

/** ``score`` null when total_count == 0; combined with
 *  ``connectNulls={false}`` on Recharts the line shows a true gap. */
export interface NPSMonthlyPoint {
  month: string; // ISO date — first day of the calendar month, UTC.
  score: number | null;
  detractor_count: number;
  passive_count: number;
  promoter_count: number;
  total_count: number;
}

/** Eight-field bundle for the dashboard top row. ``nps_score`` and
 *  ``avg_sentiment_score`` are nullable on "no data" because 0 is a
 *  meaningful value in both metrics. */
export interface HeadlineMetrics {
  total_reviews: number;
  open_tickets: number;
  today_new_tickets: number;
  crisis_count: number;
  nps_score: number | null;
  nps_coverage_percent: number;
  avg_sentiment_score: number | null;
  sensitive_topics_count: number;
}

// --- Sprint 8.3.5.6 — company-perspective distribution + taxonomy --------

export interface CompanyPerspectiveDistRow {
  code: string;
  label_tr: string;
  count: number;
  percentage: number;
}

/** ``unmatched_count`` is the share of reviews where the heuristic
 *  didn't match anything — surfaced separately from ``data`` so the
 *  /insights tab can show it as its own signal. */
export interface CompanyPerspectiveDistResponse {
  total: number;
  unmatched_count: number;
  data: CompanyPerspectiveDistRow[];
}

/** Read-only view of one row in the tenant's company-perspective
 *  taxonomy. The 8.3.7 edit UI will mutate this server-side; until
 *  then ``GET /tenants/me/taxonomies`` is the only consumer. */
export interface CategoryTaxonomyView {
  id: string;
  code: string;
  label_tr: string;
  keywords: string[];
  priority: number;
  is_default_seed: boolean;
}

// ---------------------------------------------------------------------------
// Sprint 8.3.6.6 — Strategic reports + LLM credentials + tenant profile
// ---------------------------------------------------------------------------

/** Tenant context enums — must stay in sync with imga-api's
 *  services/strategic_constants.py. The 12th industry option,
 *  ``other``, is a hybrid: when selected, ``industry_other_text``
 *  carries the free-form Türkçe label. */
export const INDUSTRY_OPTIONS: ReadonlyArray<{ code: string; label: string }> = [
  { code: "e_commerce", label: "E-ticaret" },
  { code: "retail", label: "Perakende" },
  { code: "telecom", label: "Telekomünikasyon" },
  { code: "banking", label: "Bankacılık" },
  { code: "insurance", label: "Sigortacılık" },
  { code: "services", label: "Hizmet sektörü" },
  { code: "healthcare", label: "Sağlık" },
  { code: "education", label: "Eğitim" },
  { code: "manufacturing", label: "Üretim" },
  { code: "food_beverage", label: "Yiyecek-içecek" },
  { code: "logistics", label: "Lojistik-kargo" },
  { code: "other", label: "Diğer" },
];

export const COMPANY_SIZE_OPTIONS: ReadonlyArray<{ code: string; label: string }> = [
  { code: "solo", label: "Tek kişi (1)" },
  { code: "small", label: "Küçük (2-10)" },
  { code: "medium", label: "Orta (11-50)" },
  { code: "large", label: "Büyük (51-250)" },
  { code: "enterprise", label: "Kurumsal (251+)" },
];

export interface TenantProfile {
  industry: string | null;
  industry_other_text: string | null;
  company_size: string | null;
  business_description: string | null;
}

export interface TenantProfileUpdateRequest {
  industry?: string | null;
  industry_other_text?: string | null;
  company_size?: string | null;
  business_description?: string | null;
}

// --- LLM credentials -------------------------------------------------

export interface LlmCredential {
  id: string;
  label: string;
  provider: string;
  priority: number;
  is_active: boolean;
  /** ``"...AB12"`` — last 4 chars of the plaintext, prefixed with
   *  ``...``. Backend never returns the full key after create. */
  value_preview: string;
  last_failed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface LlmCredentialCreateRequest {
  label: string;
  api_key: string;
}

export interface LlmCredentialUpdateRequest {
  label?: string;
  is_active?: boolean;
}

export interface LlmCredentialReorderRequest {
  ordered_ids: string[];
}

// --- Strategic reports -----------------------------------------------

/** SWOT row's ``output_payload`` shape. Mirrors the response_schema
 *  the backend enforces — keep both in sync. */
export interface SwotItem {
  title: string;
  description: string;
  evidence: string;
}

export interface SwotRecommendation {
  title: string;
  description: string;
  /** Backend enum: "yüksek" | "orta" | "düşük" */
  priority: string;
  /** Backend enum: "yüksek" | "orta" | "düşük" */
  estimated_impact: string;
}

export interface SwotPayload {
  strengths: SwotItem[];
  weaknesses: SwotItem[];
  opportunities: SwotItem[];
  threats: SwotItem[];
  strategic_recommendations: SwotRecommendation[];
}

/** OKR row's ``output_payload`` shape. */
export interface OkrKeyResult {
  text: string;
  metric: string;
  baseline: string;
  target: string;
}

export interface OkrObjective {
  objective: string;
  rationale: string;
  key_results: OkrKeyResult[];
}

export interface OkrPayload {
  objectives: OkrObjective[];
}

export type StrategicReportType = "swot" | "okr";

export interface StrategicReportSummary {
  id: string;
  report_type: StrategicReportType;
  date_from: string | null;
  date_to: string | null;
  source_report_id: string | null;
  model_name: string;
  generation_duration_ms: number | null;
  created_at: string;
}

export interface StrategicReportDetail {
  id: string;
  report_type: StrategicReportType;
  date_from: string | null;
  date_to: string | null;
  source_report_id: string | null;
  input_stats: Record<string, unknown>;
  output_payload: Record<string, unknown>;
  model_name: string;
  token_usage: { input: number; output: number; total: number } | null;
  generation_duration_ms: number | null;
  created_at: string;
  created_by_user_id: string | null;
}

export interface StrategicReportListResponse {
  items: StrategicReportSummary[];
  total: number;
  has_more: boolean;
}

export interface SwotGenerateRequest {
  date_from?: string | null; // YYYY-MM-DD
  date_to?: string | null;
  force_refresh?: boolean;
  /** Sprint 8.3.11 — optional batch scope. When set, the SWOT
   *  reflects only that upload's reviews. */
  batch_id?: string | null;
}

export interface OkrGenerateRequest {
  source_report_id: string;
}

// ---------------------------------------------------------------------------
// Sprint 8.3.7-A — taxonomy edit + SLA rules
// ---------------------------------------------------------------------------

/** Mirrors imga-api ``TaxonomyEntryResponse``. ``is_default_seed`` is
 *  the wire/storage field name; the UI labels it as "Sistem" in
 *  Türkçe copy (the pre-existing /reviews + /insights pages already
 *  read the same column under the same name, so the frontend stays
 *  consistent across consumers). */
export interface TaxonomyEntry {
  id: string;
  code: string;
  label_tr: string;
  keywords: string[];
  priority: number;
  parent_code: string | null;
  is_default_seed: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface TaxonomyCreateRequest {
  code: string;
  label_tr: string;
  keywords?: string[];
  priority?: number;
  parent_code?: string | null;
}

export interface TaxonomyUpdateRequest {
  label_tr?: string;
  keywords?: string[];
  priority?: number;
  parent_code?: string | null;
}

export interface TaxonomyReorderRequest {
  ordered_ids: string[];
}

export type SlaPriority = "low" | "normal" | "high" | "urgent";
export type SlaActionType =
  | "warn_only"
  | "create_ticket"
  | "escalate"
  | "notify_email";

export const SLA_ACTION_LABELS: Record<SlaActionType, string> = {
  warn_only: "Uyarı (sadece logla)",
  create_ticket: "Bilet oluştur",
  escalate: "Yükselt",
  notify_email: "E-posta gönder",
};

export const SLA_ACTION_AVAILABLE_NOW: ReadonlySet<SlaActionType> = new Set([
  "warn_only",
]);

export interface SlaRule {
  id: string;
  name: string;
  match_priority: SlaPriority | null;
  match_taxonomy_codes: string[] | null;
  match_company_perspective_codes: string[] | null;
  match_nps_score_max: number | null;
  response_sla_minutes: number | null;
  resolution_sla_minutes: number | null;
  action_type: SlaActionType;
  action_config: Record<string, unknown>;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface SlaRuleCreateRequest {
  name: string;
  match_priority?: SlaPriority | null;
  match_taxonomy_codes?: string[] | null;
  match_company_perspective_codes?: string[] | null;
  match_nps_score_max?: number | null;
  response_sla_minutes?: number | null;
  resolution_sla_minutes?: number | null;
  action_type?: SlaActionType;
  action_config?: Record<string, unknown>;
  is_active?: boolean;
}

export interface SlaRuleUpdateRequest {
  name?: string;
  match_priority?: SlaPriority | null;
  match_taxonomy_codes?: string[] | null;
  match_company_perspective_codes?: string[] | null;
  match_nps_score_max?: number | null;
  response_sla_minutes?: number | null;
  resolution_sla_minutes?: number | null;
  action_type?: SlaActionType;
  action_config?: Record<string, unknown>;
  is_active?: boolean;
}

// ---------------------------------------------------------------------------
// Sprint 8.3.8 — smart parser preview
// ---------------------------------------------------------------------------

/** Logical field name the smart_parser can recognise. ``ignore`` is
 *  a frontend-only sentinel for the manual-override dropdown
 *  ("don't import this column"). */
export type SmartFieldName =
  | "review_text"
  | "nps_score"
  | "date"
  | "customer_id"
  | "order_id"
  | "product_name"
  | "customer_name"
  | "price"
  | "ignore";

export const SMART_FIELD_LABELS: Record<SmartFieldName, string> = {
  review_text: "Yorum",
  nps_score: "NPS Skoru",
  date: "Tarih",
  customer_id: "Müşteri ID",
  order_id: "Sipariş ID",
  product_name: "Ürün Adı",
  customer_name: "Müşteri Adı",
  price: "Fiyat",
  ignore: "Yoksay",
};

/** UI confidence bands — must stay in sync with imga_api.services
 *  .smart_parser.types CONFIDENCE_HIGH / MEDIUM / LOW. */
export const CONFIDENCE_HIGH = 0.85;
export const CONFIDENCE_MEDIUM = 0.55;
export const CONFIDENCE_LOW = 0.3;

export interface DetectorAlternative {
  field_name: SmartFieldName;
  confidence: number;
}

export interface DetectedColumn {
  column_name: string;
  field_name: SmartFieldName | null;
  confidence: number;
  sample_values: string[];
  alternatives: DetectorAlternative[];
  metadata: Record<string, unknown>;
}

export interface SmartPreviewResponse {
  headers: string[];
  row_count: number;
  detected: DetectedColumn[];
  /** ``"<field>:<column_header>"`` strings — when this list is non-
   *  empty the UI shows the PII consent banner before the upload
   *  proceeds. Today only customer_name emits these. */
  pii_warnings: string[];
}

// ---------------------------------------------------------------------------
// Sprint 8.3.9 — insights expansion (cohort, word cloud, heatmap)
// ---------------------------------------------------------------------------

export type CohortPeriod = "week" | "month" | "quarter";
export type CohortDimension = "taxonomy" | "company_perspective" | "nps_bucket";

export interface CohortDataPoint {
  period_start: string;
  count: number;
  avg_sentiment: number | null;
  avg_nps: number | null;
}

export interface CohortSeries {
  key: string;
  label: string;
  data_points: CohortDataPoint[];
}

export interface CohortResponse {
  period: CohortPeriod;
  dimension: CohortDimension;
  cohorts: CohortSeries[];
}

export type WordCloudSentiment = "positive" | "negative" | "neutral" | "all";

export interface WordCloudWord {
  text: string;
  weight: number;
  sentiment_skew: number;
  is_bigram: boolean;
}

export interface WordCloudResponse {
  words: WordCloudWord[];
  total_reviews_analyzed: number;
}

export type HeatmapXAxis = "hour_of_day" | "day_of_week" | "week_of_year";
export type HeatmapYAxis = "day_of_week" | "month" | "taxonomy_code";
export type HeatmapMetric = "count" | "avg_sentiment" | "avg_nps";

export interface HeatmapResponse {
  x_axis: HeatmapXAxis;
  y_axis: HeatmapYAxis;
  metric: HeatmapMetric;
  metric_label: string;
  x_labels: string[];
  y_labels: string[];
  values: Array<Array<number | null>>;
  metric_min: number;
  metric_max: number;
}

// ---------------------------------------------------------------------------
// Sprint 8.3.10 — executive briefing + action items + trend alerts
// ---------------------------------------------------------------------------

export type BriefingPeriod = "week" | "month" | "quarter";

export const BRIEFING_PERIOD_LABELS: Record<BriefingPeriod, string> = {
  week: "Hafta",
  month: "Ay",
  quarter: "Çeyrek",
};

export interface BriefingKpiChange {
  metric: string;
  current: number;
  previous: number;
  /** Sprint 8.3.11 R2 — null when ``previous`` was 0 or missing
   *  (the server-side computer flags these with ``change_label =
   *  "yeni başlangıç"`` so the UI renders the no-comparison state). */
  change_pct: number | null;
  change_label?: string | null;
  direction: "up" | "down" | "flat";
}

export interface BriefingTopAction {
  title: string;
  rationale: string;
}

export interface ExecutiveBriefing {
  id: string;
  period: BriefingPeriod;
  date_from: string;
  date_to: string;
  batch_id: string | null;
  headline: string;
  kpi_changes: BriefingKpiChange[];
  critical_insights: string[];
  top_actions: BriefingTopAction[];
  model_name: string;
  token_usage: { input: number; output: number; total: number } | null;
  generated_at: string;
}

export interface BriefingListItem {
  id: string;
  period: BriefingPeriod;
  date_from: string;
  date_to: string;
  batch_id: string | null;
  headline: string;
  model_name: string;
  generated_at: string;
}

export interface BriefingGenerateRequest {
  period: BriefingPeriod;
  date_from?: string | null;
  date_to?: string | null;
  batch_id?: string | null;
  force_refresh?: boolean;
}

export type ActionItemStatus = "open" | "in_progress" | "done" | "cancelled";
export type ActionItemPriority = "high" | "medium" | "low";

export const ACTION_ITEM_STATUS_LABELS: Record<ActionItemStatus, string> = {
  open: "Açık",
  in_progress: "Devam Ediyor",
  done: "Tamamlandı",
  cancelled: "İptal",
};

export const ACTION_ITEM_PRIORITY_LABELS: Record<ActionItemPriority, string> = {
  high: "Yüksek",
  medium: "Orta",
  low: "Düşük",
};

export interface ActionItem {
  id: string;
  title: string;
  description: string;
  rationale: string | null;
  priority: ActionItemPriority;
  estimated_impact: ActionItemPriority | null;
  status: ActionItemStatus;
  source_report_id: string | null;
  source_briefing_id: string | null;
  assignee_user_id: string | null;
  due_date: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  // Sprint 9.1 A — soft-delete state.
  is_archived: boolean;
  archived_at: string | null;
  archived_by: string | null;
}

export type ActionItemActorType =
  | "user"
  | "system"
  | "llm_extraction"
  | "briefing_pipeline";

export type ActionItemEventType =
  | "created"
  | "updated"
  | "archived"
  | "unarchived"
  | "status_changed"
  | "priority_changed"
  | "assigned"
  | "unassigned"
  | "commented";

export interface ActionItemEvent {
  id: string;
  event_type: ActionItemEventType;
  actor_user_id: string | null;
  actor_type: ActionItemActorType;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface ActionItemCreateRequest {
  title: string;
  description: string;
  rationale?: string | null;
  priority?: ActionItemPriority;
  estimated_impact?: ActionItemPriority | null;
  assignee_user_id?: string | null;
  due_date?: string | null;
}

export interface ActionItemUpdateRequest {
  title?: string;
  description?: string;
  rationale?: string | null;
  priority?: ActionItemPriority;
  estimated_impact?: ActionItemPriority | null;
  status?: ActionItemStatus;
  assignee_user_id?: string | null;
  due_date?: string | null;
}

export type TrendAlertStatus = "active" | "acknowledged" | "dismissed";
export type TrendAlertSeverity = "info" | "warning" | "critical";

export const TREND_ALERT_SEVERITY_LABELS: Record<TrendAlertSeverity, string> = {
  info: "Bilgi",
  warning: "Uyarı",
  critical: "Kritik",
};

export interface TrendAlert {
  id: string;
  alert_type: string;
  severity: TrendAlertSeverity;
  title: string;
  description: string;
  evidence: Record<string, unknown>;
  status: TrendAlertStatus;
  acknowledged_by_user_id: string | null;
  acknowledged_at: string | null;
  created_at: string;
}
