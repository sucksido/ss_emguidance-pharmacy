import { HttpClient, HttpHeaders, HttpParams, HttpResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import {
  Dispense,
  DispenseRequest,
  Medicine,
  MedicineDetail,
  NewRule,
  Page,
  RuleHistory,
  SupersedeResult,
} from './api.types';

const BASE = '/api/v1';
/** Stub identity (auth is out of scope); recorded by the API for audit. */
const ACTOR = new HttpHeaders({ 'X-Actor': 'web-ui' });

function params(obj: Record<string, string | number | null | undefined>): HttpParams {
  let p = new HttpParams();
  for (const [k, v] of Object.entries(obj)) {
    if (v !== null && v !== undefined && v !== '') p = p.set(k, String(v));
  }
  return p;
}

@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);

  searchMedicines(q: string, cursor: string | null, limit = 20): Observable<Page<Medicine>> {
    return this.http.get<Page<Medicine>>(`${BASE}/medicines`, { params: params({ q, cursor, limit }) });
  }

  medicine(code: string): Observable<MedicineDetail> {
    return this.http.get<MedicineDetail>(`${BASE}/medicines/${encodeURIComponent(code)}`);
  }

  rules(code: string): Observable<RuleHistory> {
    return this.http.get<RuleHistory>(`${BASE}/medicines/${encodeURIComponent(code)}/rules`);
  }

  addRule(code: string, rule: NewRule): Observable<SupersedeResult> {
    return this.http.post<SupersedeResult>(`${BASE}/medicines/${encodeURIComponent(code)}/rules`, rule, {
      headers: ACTOR,
    });
  }

  /** Full response so the caller can read the Idempotent-Replayed header. */
  dispense(body: DispenseRequest): Observable<HttpResponse<Dispense>> {
    return this.http.post<Dispense>(`${BASE}/dispenses`, body, { headers: ACTOR, observe: 'response' });
  }

  dispenses(
    filters: { patient_ref?: string; medicine_code?: string },
    cursor: string | null,
    limit = 20,
  ): Observable<Page<Dispense>> {
    return this.http.get<Page<Dispense>>(`${BASE}/dispenses`, { params: params({ ...filters, cursor, limit }) });
  }
}
