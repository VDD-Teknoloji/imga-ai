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
