import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { forkJoin } from 'rxjs';
import { ApiService } from '../core/api.service';
import { ErrorItem, NewRule, Problem, Rule } from '../core/api.types';
import { applyServerErrors, serverErrors, toProblem } from '../core/problem';
import { formColor } from './form-colors';
import { ProblemBanner } from './problem-banner';

const DAY = 86_400_000;
const toMs = (d: string) => Date.parse(`${d}T00:00:00Z`);
/** effective_to is exclusive; people read "last day in force". */
export const lastDay = (exclusiveTo: string) => new Date(toMs(exclusiveTo) - DAY).toISOString().slice(0, 10);

interface Segment {
  rule: Rule;
  left: number;
  width: number;
}

/** View 2: medicine, rule history as a timeline, and the "introduce a rule" operation. */
@Component({
  selector: 'app-medicine-detail',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, ReactiveFormsModule, ProblemBanner],
  template: `
    <a class="crumb" routerLink="/medicines">← All medicines</a>
    <app-problem-banner [problem]="loadError()" />

    @if (data.value(); as d) {
      <div class="card med-hero">
        <div class="med-icon" [style.color]="color(d.medicine.form)">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m10.5 20.5 10-10a4.95 4.95 0 1 0-7-7l-10 10a4.95 4.95 0 1 0 7 7Z"/><path d="m8.5 8.5 7 7"/></svg>
        </div>
        <div>
          <h1>{{ d.medicine.name }}</h1>
          <div class="med-meta">
            <span class="code-chip">{{ d.medicine.code }}</span>
            <span class="form-pill"><i [style.background]="color(d.medicine.form)"></i>{{ d.medicine.form }}</span>
            <span class="dot"></span>
            <span>{{ +d.medicine.strength_value }} {{ d.medicine.strength_unit }}</span>
            <span class="dot"></span>
            @if (d.medicine.is_active) { <span class="badge ok">Active</span> }
            @else { <span class="badge muted">Inactive · cannot be dispensed</span> }
          </div>
        </div>
        <div class="actions">
          <a class="btn" [routerLink]="['/dispense']" [queryParams]="{ medicine: d.medicine.code }">+ Dispense</a>
        </div>
      </div>

      <div class="section">
        <h2>Rule in force today <span class="hint">· {{ d.history.business_date }}, Africa/Johannesburg</span></h2>
        @if (d.medicine.current_rule; as r) {
          <div class="kpis">
            <div class="kpi accent">
              <div class="label">Max per dispense</div>
              <div class="value">{{ r.max_quantity_per_dispense }}<small>units</small></div>
              <div class="sub">Rule #{{ r.id }}</div>
            </div>
            <div class="kpi">
              <div class="label">Max per 30 days</div>
              <div class="value">{{ r.max_quantity_per_30_days }}<small>units / patient</small></div>
              <div class="sub">Rolling, by business day</div>
            </div>
            <div class="kpi">
              <div class="label">Authorisation</div>
              <div class="value" style="font-size:20px; margin-top:10px">
                @if (r.requires_authorisation) { <span class="badge scheduled">Required</span> }
                @else { <span class="badge ok">Not required</span> }
              </div>
            </div>
            <div class="kpi">
              <div class="label">In force since</div>
              <div class="value" style="font-size:20px; margin-top:8px">{{ r.effective_from }}</div>
              <div class="sub">{{ r.effective_to ? 'until ' + lastDay(r.effective_to) : 'open-ended' }}</div>
            </div>
          </div>
        } @else {
          <div class="alert warn"><span class="icon">!</span><div><strong>No rule is in force today</strong>Dispenses dated today will be rejected for this medicine.</div></div>
        }
      </div>

      <div class="card section">
        <div class="card-head">
          <div><h2>Rule history</h2><p>Every rule ever applied to this medicine. Past rules are kept, never edited.</p></div>
          <div class="legend">
            <span><i style="background:#e2e8f0"></i>Past</span>
            <span><i style="background:var(--brand-600)"></i>In force</span>
            <span><i style="background:#fde68a"></i>Scheduled</span>
          </div>
        </div>
        <div class="card-body">
          <div class="timeline" aria-hidden="true">
            <div class="track"></div>
            @for (s of segments(); track s.rule.id) {
              <div class="seg" [class]="s.rule.status" [style.left.%]="s.left" [style.width.%]="s.width"
                   [title]="'Rule #' + s.rule.id + ': ' + s.rule.effective_from + ' → ' + (s.rule.effective_to ?? 'open')">
                {{ s.rule.max_quantity_per_dispense }} / {{ s.rule.max_quantity_per_30_days }}
              </div>
            }
            @for (t of ticks(); track t.label) { <span class="tick" [style.left.%]="t.pos">{{ t.label }}</span> }
            <div class="today" [style.left.%]="todayPos()"></div>
          </div>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr><th>Rule</th><th>From</th><th>Last day</th><th class="num">Per dispense</th><th class="num">Per 30 days</th><th>Authorisation</th><th>Status</th></tr>
            </thead>
            <tbody>
              @for (r of d.history.items; track r.id) {
                <tr [class.in-force]="r.status === 'in_force'">
                  <td class="mono">#{{ r.id }}</td>
                  <td>{{ r.effective_from }}</td>
                  <td>{{ r.effective_to ? lastDay(r.effective_to) : 'open-ended' }}</td>
                  <td class="num cell-title">{{ r.max_quantity_per_dispense }}</td>
                  <td class="num cell-title">{{ r.max_quantity_per_30_days }}</td>
                  <td>{{ r.requires_authorisation ? 'Required' : '—' }}</td>
                  <td>
                    <span class="badge" [class]="r.status">{{ statusLabel[r.status] }}</span>
                    @if (r.superseded_by_id) { <div class="cell-sub">superseded by #{{ r.superseded_by_id }}</div> }
                  </td>
                </tr>
              } @empty {
                <tr><td colspan="7" class="empty"><strong>No rules yet</strong>Introduce the first rule below.</td></tr>
              }
            </tbody>
          </table>
        </div>
      </div>

      <div class="card section">
        <div class="card-head">
          <div>
            <h2>Introduce a rule</h2>
            <p>The rule in force on the start date ends the day before; the new rule takes over the rest of its period.
              A change that would alter the rule behind an existing dispense is refused.</p>
          </div>
        </div>
        <form class="card-body" [formGroup]="ruleForm" (ngSubmit)="addRule()">
          <div class="form-grid">
            <label>Effective from <input type="date" formControlName="effective_from" />
              @for (e of fieldErrors('effective_from'); track $index) { <span class="err">{{ e.message }}</span> }
            </label>
            <label><span class="label-text">Effective to <small>exclusive · optional</small></span> <input type="date" formControlName="effective_to" />
              @for (e of fieldErrors('effective_to'); track $index) { <span class="err">{{ e.message }}</span> }
            </label>
            <label>Max per dispense <input type="number" min="1" formControlName="max_quantity_per_dispense" />
              @for (e of fieldErrors('max_quantity_per_dispense'); track $index) { <span class="err">{{ e.message }}</span> }
            </label>
            <label>Max per 30 days <input type="number" min="1" formControlName="max_quantity_per_30_days" />
              @for (e of fieldErrors('max_quantity_per_30_days'); track $index) { <span class="err">{{ e.message }}</span> }
            </label>
            <label class="check full"><input type="checkbox" formControlName="requires_authorisation" /> Requires an authorisation reference</label>
            <div class="actions full">
              <button type="submit" [disabled]="ruleForm.invalid || saving()">
                @if (saving()) { <span class="spinner"></span> Saving… } @else { Introduce rule }
              </button>
            </div>
          </div>
          <app-problem-banner [problem]="ruleProblem()" />
          @if (ruleSaved(); as msg) { <div class="alert ok"><span class="icon">✓</span><div>{{ msg }}</div></div> }
        </form>
      </div>
    } @else if (data.isLoading()) {
      <div class="card med-hero"><p class="hint">Loading medicine…</p></div>
    }
  `,
})
export class MedicineDetailPage {
  private readonly api = inject(ApiService);
  private readonly fb = inject(FormBuilder);

  /** Bound from the :code route parameter (withComponentInputBinding). */
  readonly code = input.required<string>();
  readonly lastDay = lastDay;
  readonly color = formColor;
  readonly statusLabel: Record<string, string> = { past: 'Past', in_force: 'In force', scheduled: 'Scheduled' };

  readonly data = rxResource({
    params: () => this.code(),
    stream: ({ params: code }) => forkJoin({ medicine: this.api.medicine(code), history: this.api.rules(code) }),
  });
  readonly loadError = computed<Problem | null>(() => (this.data.error() ? toProblem(this.data.error()) : null));

  private readonly range = computed(() => {
    const d = this.data.value();
    if (!d || !d.history.items.length) return null;
    const today = toMs(d.history.business_date);
    const items = d.history.items;
    const start = toMs(items[0].effective_from);
    const lastTo = items[items.length - 1].effective_to;
    const end = Math.max(today + 90 * DAY, lastTo ? toMs(lastTo) : 0, toMs(items[items.length - 1].effective_from) + 90 * DAY);
    return { start, end, today };
  });

  readonly segments = computed<Segment[]>(() => {
    const r = this.range();
    const d = this.data.value();
    if (!r || !d) return [];
    const span = r.end - r.start;
    return d.history.items.map((rule) => {
      const from = toMs(rule.effective_from);
      const to = rule.effective_to ? toMs(rule.effective_to) : r.end;
      return { rule, left: ((from - r.start) / span) * 100, width: ((to - from) / span) * 100 };
    });
  });

  /** Year (and mid-year) markers under the timeline. */
  readonly ticks = computed(() => {
    const r = this.range();
    if (!r) return [];
    const out: { label: string; pos: number }[] = [];
    const first = new Date(r.start).getUTCFullYear();
    const last = new Date(r.end).getUTCFullYear();
    for (let y = first; y <= last + 1; y++) {
      for (const m of [0, 6]) {
        const t = Date.UTC(y, m, 1);
        if (t > r.start && t < r.end) {
          out.push({ label: m === 0 ? String(y) : `Jul ${y}`, pos: ((t - r.start) / (r.end - r.start)) * 100 });
        }
      }
    }
    return out;
  });

  readonly todayPos = computed(() => {
    const r = this.range();
    return r ? ((r.today - r.start) / (r.end - r.start)) * 100 : 0;
  });

  readonly ruleForm = this.fb.nonNullable.group({
    effective_from: ['', Validators.required],
    effective_to: [''],
    max_quantity_per_dispense: [30, [Validators.required, Validators.min(1)]],
    max_quantity_per_30_days: [90, [Validators.required, Validators.min(1)]],
    requires_authorisation: [false],
  });
  readonly saving = signal(false);
  readonly ruleProblem = signal<Problem | null>(null);
  readonly ruleSaved = signal<string | null>(null);

  fieldErrors(name: string): ErrorItem[] {
    return serverErrors(this.ruleForm.get(name));
  }

  addRule(): void {
    const v = this.ruleForm.getRawValue();
    const body: NewRule = { ...v, effective_to: v.effective_to || null };
    this.saving.set(true);
    this.ruleProblem.set(null);
    this.ruleSaved.set(null);
    this.api.addRule(this.code(), body).subscribe({
      next: (res) => {
        this.saving.set(false);
        this.ruleSaved.set(
          `Rule #${res.rule.id} introduced from ${res.rule.effective_from}` +
            (res.superseded_rule ? `; rule #${res.superseded_rule.id} now ends ${res.rule.effective_from}.` : '.'),
        );
        this.data.reload();
      },
      error: (err) => {
        this.saving.set(false);
        const p = toProblem(err);
        applyServerErrors(this.ruleForm, p.errors);
        this.ruleProblem.set(p);
      },
    });
  }
}
