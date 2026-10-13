import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { forkJoin } from 'rxjs';
import { ApiService } from '../core/api.service';
import { ErrorItem, NewRule, Problem, Rule } from '../core/api.types';
import { applyServerErrors, serverErrors, toProblem } from '../core/problem';
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
    <p><a routerLink="/medicines">← Medicines</a></p>
    <app-problem-banner [problem]="loadError()" />

    @if (data.value(); as d) {
      <h1>{{ d.medicine.name }} <small>{{ d.medicine.code }}</small></h1>
      <p>
        {{ d.medicine.form }} · {{ +d.medicine.strength_value }} {{ d.medicine.strength_unit }} ·
        @if (d.medicine.is_active) { <span class="chip ok">active</span> }
        @else { <span class="chip muted">inactive — cannot be dispensed</span> }
        · <a [routerLink]="['/dispense']" [queryParams]="{ medicine: d.medicine.code }">Dispense this medicine</a>
      </p>

      <h2>Rule in force today <small>({{ d.history.business_date }}, Africa/Johannesburg)</small></h2>
      @if (d.medicine.current_rule; as r) {
        <p class="current">
          Max <strong>{{ r.max_quantity_per_dispense }}</strong> per dispense ·
          <strong>{{ r.max_quantity_per_30_days }}</strong> per patient per 30 days ·
          {{ r.requires_authorisation ? 'authorisation required' : 'no authorisation needed' }}
        </p>
      } @else {
        <p class="problem">No rule is in force today: dispenses dated today will be rejected.</p>
      }

      <h2>Rule history</h2>
      <div class="timeline" aria-hidden="true">
        @for (s of segments(); track s.rule.id) {
          <div class="seg" [class]="s.rule.status" [style.left.%]="s.left" [style.width.%]="s.width"
               [title]="'Rule ' + s.rule.id + ': ' + s.rule.effective_from + ' → ' + (s.rule.effective_to ?? 'open')">
            {{ s.rule.max_quantity_per_dispense }}/{{ s.rule.max_quantity_per_30_days }}
          </div>
        }
        <div class="today" [style.left.%]="todayPos()" title="today"></div>
      </div>
      <table>
        <thead>
          <tr><th>Rule</th><th>From</th><th>Last day</th><th>Per dispense</th><th>Per 30 days</th><th>Auth</th><th>Status</th></tr>
        </thead>
        <tbody>
          @for (r of d.history.items; track r.id) {
            <tr [class.in-force]="r.status === 'in_force'">
              <td>#{{ r.id }}</td>
              <td>{{ r.effective_from }}</td>
              <td>{{ r.effective_to ? lastDay(r.effective_to) : 'open-ended' }}</td>
              <td>{{ r.max_quantity_per_dispense }}</td>
              <td>{{ r.max_quantity_per_30_days }}</td>
              <td>{{ r.requires_authorisation ? 'yes' : 'no' }}</td>
              <td>
                <span class="chip" [class]="r.status">{{ r.status === 'in_force' ? 'IN FORCE' : r.status }}</span>
                @if (r.superseded_by_id) { <small>superseded by #{{ r.superseded_by_id }}</small> }
              </td>
            </tr>
          } @empty {
            <tr><td colspan="7" class="empty">No rules yet.</td></tr>
          }
        </tbody>
      </table>

      <h2>Introduce a rule</h2>
      <p class="hint">
        The rule in force on the start date is ended the day before and the new rule takes over the rest of
        its period. History is never rewritten: a start date that would change the rule behind an existing
        dispense is refused.
      </p>
      <form [formGroup]="ruleForm" (ngSubmit)="addRule()" class="grid">
        <label>Effective from <input type="date" formControlName="effective_from" />
          @for (e of fieldErrors('effective_from'); track $index) { <span class="err">{{ e.message }}</span> }
        </label>
        <label>Effective to (exclusive, optional) <input type="date" formControlName="effective_to" />
          @for (e of fieldErrors('effective_to'); track $index) { <span class="err">{{ e.message }}</span> }
        </label>
        <label>Max per dispense <input type="number" min="1" formControlName="max_quantity_per_dispense" />
          @for (e of fieldErrors('max_quantity_per_dispense'); track $index) { <span class="err">{{ e.message }}</span> }
        </label>
        <label>Max per 30 days <input type="number" min="1" formControlName="max_quantity_per_30_days" />
          @for (e of fieldErrors('max_quantity_per_30_days'); track $index) { <span class="err">{{ e.message }}</span> }
        </label>
        <label class="check"><input type="checkbox" formControlName="requires_authorisation" /> Requires authorisation</label>
        <div>
          <button type="submit" [disabled]="ruleForm.invalid || saving()">{{ saving() ? 'Saving…' : 'Introduce rule' }}</button>
        </div>
      </form>
      <app-problem-banner [problem]="ruleProblem()" />
      @if (ruleSaved(); as msg) { <p class="ok-msg">{{ msg }}</p> }
    } @else if (data.isLoading()) {
      <p>Loading…</p>
    }
  `,
})
export class MedicineDetailPage {
  private readonly api = inject(ApiService);
  private readonly fb = inject(FormBuilder);

  /** Bound from the :code route parameter (withComponentInputBinding). */
  readonly code = input.required<string>();
  readonly lastDay = lastDay;

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
