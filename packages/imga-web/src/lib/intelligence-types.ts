export interface PrdSection {
  id: string;
  title: string;
  question: string;
  answer: string;
  evidence: string;
  acceptance: string;
  owner: string;
  status: "open" | "draft" | "confirmed" | "not_applicable";
}
export interface PrdDocument {
  title: string;
  sections: PrdSection[];
}
export interface OrgUnit {
  id: string;
  name: string;
  parent_id: string | null;
  accountable_role: string;
  mandate: string;
}
export interface ProcessStep {
  name: string;
  owner_unit_id: string | null;
  target_minutes: number | null;
}
export interface CompanyProcess {
  id: string;
  name: string;
  owner_unit_id: string | null;
  category_codes: string[];
  steps: ProcessStep[];
  resolution_target_minutes: number | null;
  escalation: string;
  source: string;
  verified_on: string | null;
}
export interface CompanyContext {
  name: string;
  purpose: string;
  business_model: string;
  markets: string[];
  timezone: string;
  analysis_profile: "tr" | "mena";
  report_language: "tr" | "en" | "ar" | "ur";
  units: OrgUnit[];
  processes: CompanyProcess[];
  constraints: string;
}
export interface Interview {
  questions: { section_id: string; field: string; question: string }[];
  maturity_percent: number;
  confirmed: number;
  total: number;
  ready_for_approval: boolean;
}
export interface DocumentSnapshot<T> {
  kind: "company" | "prd";
  revision: number;
  status: "draft" | "approved";
  content: T;
  created_at: string | null;
  actor_id: string | null;
  interview?: Interview;
}
export interface CustomerProfile {
  external_id: string;
  name: string;
  segment: string;
  source: string;
  observed_on: string;
  lifecycle: "active" | "paused" | "churned";
  last_activity_on: string | null;
  expected_activity_days: number | null;
  orders_current_30d: number | null;
  orders_previous_30d: number | null;
  usage_current_30d: number | null;
  usage_previous_30d: number | null;
  overdue_invoices: number | null;
  cancellation_requested: boolean | null;
  renewal_on: string | null;
  annual_revenue: string | null;
  currency: string | null;
  owner: string;
  next_action: string;
  follow_up_on: string | null;
  outcome: "open" | "contacted" | "retained" | "lost" | "monitoring";
}
export type RiskBand = "unknown" | "low" | "watch" | "high" | "critical" | "inactive";
export interface CustomerRisk {
  score: number | null;
  band: RiskBand;
  data_status: string;
  as_of: string;
  observed_domains: number;
  missing: string[];
  signals: { code: string; points: number; evidence: string; recommendation: string }[];
  review_signals: { total: number; negative: number; sla_violations: number; low_nps: number };
}
export interface CustomerRecord {
  revision: number;
  profile: CustomerProfile;
  risk: CustomerRisk;
  created_at?: string;
}
export interface CustomerList {
  items: CustomerRecord[];
  total: number;
  account_count: number;
  capacity: number;
  counts: Partial<Record<RiskBand, number>>;
  page: number;
  page_size: number;
}
export interface CompanyDiagnostics {
  published_revision: number;
  as_of: string;
  data_status: string;
  findings: {
    code: string;
    kind: string;
    subject: string;
    evidence: string;
    recommendation: string;
  }[];
  review_count: number;
  mapped_review_count: number;
  unmapped_review_count: number;
  process_metrics: {
    process_id: string;
    samples: number;
    above_target: number;
    target_minutes: number;
    status: string;
  }[];
}
