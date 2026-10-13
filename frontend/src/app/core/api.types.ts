/** Mirrors of the API's JSON shapes (backend/app/schemas.py, backend/app/errors.py). */

export interface ErrorItem {
  code: string;
  field: string | null;
  message: string;
  rule_id: number | null;
  meta: Record<string, unknown>;
}

/** RFC 9457 problem document + `code` and `errors` extensions. */
export interface Problem {
  type: string;
  title: string;
  status: number;
  code: string;
  detail: string | null;
  instance: string;
  errors: ErrorItem[];
  attempt_id?: number;
  business_date?: string;
}

export interface Page<T> {
  items: T[];
  page: { limit: number; has_more: boolean; next_cursor: string | null };
}

export interface Medicine {
  code: string;
  name: string;
  form: string;
  strength_value: string;
  strength_unit: string;
  is_active: boolean;
}

export type RuleStatus = 'past' | 'in_force' | 'scheduled';

export interface Rule {
  id: number;
  effective_from: string;
  effective_to: string | null; // exclusive
  max_quantity_per_dispense: number;
  max_quantity_per_30_days: number;
  requires_authorisation: boolean;
  superseded_by_id: number | null;
  created_at: string;
  created_by: string | null;
  status: RuleStatus;
}

export interface MedicineDetail extends Medicine {
  current_rule: Rule | null;
  business_date: string;
}

export interface RuleHistory {
  medicine_code: string;
  business_date: string;
  in_force_rule_id: number | null;
  items: Rule[];
}

export interface NewRule {
  effective_from: string;
  effective_to?: string | null;
  max_quantity_per_dispense: number;
  max_quantity_per_30_days: number;
  requires_authorisation: boolean;
}

export interface SupersedeResult {
  rule: Rule;
  superseded_rule: Rule | null;
}

export interface DispenseRequest {
  medicine_code: string;
  patient_ref: string;
  quantity: number;
  dispensed_at: string;
  authorisation_ref: string | null;
  idempotency_key: string;
}

export interface Dispense {
  id: number;
  medicine_code: string;
  medicine_name: string;
  patient_ref: string;
  quantity: number;
  dispensed_at: string;
  business_date: string;
  authorisation_ref: string | null;
  formulary_rule_id: number;
  idempotency_key: string;
  recorded_at: string;
}
