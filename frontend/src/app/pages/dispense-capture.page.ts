import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { catchError, debounceTime, distinctUntilChanged, map, of, switchMap } from 'rxjs';
import { ApiService } from '../core/api.service';
import { Dispense, DispenseRequest, ErrorItem, MedicineDetail, Problem } from '../core/api.types';
import { applyServerErrors, serverErrors, toProblem } from '../core/problem';
import { formatBusinessTime, nowWallClock, wallClockToIso } from '../core/sast-time';
import { ProblemBanner } from './problem-banner';

type Phase = 'editing' | 'submitting' | 'accepted' | 'rejected' | 'failed';

/**
 * View 3. State model:
 *
 * - `idempotencyKey` identifies the user's *intent*, not the HTTP call. It is
 *   kept across retries after a network failure or 5xx (so a retry can never
 *   double-dispense) and replaced as soon as the user edits the form after a
 *   definitive answer (201 or 422), because that is a new intent.
 * - Server errors are attached to the control named by their `field`; errors
 *   with no matching control are shown at form level. The summary lists every
 *   error regardless, so multiple simultaneous reasons are always visible.
 */
@Component({
  selector: 'app-dispense-capture',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, RouterLink, ProblemBanner],
  template: `
    <div class="page-head">
      <div>
        <h1>Capture dispense</h1>
        <p>Validated against the formulary rule in force at the dispense time. Backdating is allowed.</p>
      </div>
    </div>

    <div class="split">
      <div>
        <form class="card" [formGroup]="form" (ngSubmit)="submit()" novalidate>
          <div class="card-head"><div><h2>Dispense details</h2><p>All times are Africa/Johannesburg.</p></div></div>
          <div class="card-body">
            <div class="form-grid">
              <label>Medicine code
                <input formControlName="medicine_code" placeholder="MED000001" autocomplete="off" class="mono" />
                @for (e of fieldErrors('medicine_code'); track $index) { <span class="err">{{ e.message }}</span> }
              </label>
              <label>Patient reference
                <input formControlName="patient_ref" placeholder="PT-0000001" autocomplete="off" class="mono" />
                @for (e of fieldErrors('patient_ref'); track $index) { <span class="err">{{ e.message }}</span> }
              </label>
              <label><span class="label-text">Quantity <small>units</small></span>
                <input type="number" min="1" step="1" formControlName="quantity" />
                @for (e of fieldErrors('quantity'); track $index) { <span class="err">{{ e.message }}</span> }
              </label>
              <label><span class="label-text">Dispensed at <small>may be backdated</small></span>
                <input type="datetime-local" formControlName="dispensed_at" />
                @for (e of fieldErrors('dispensed_at'); track $index) { <span class="err">{{ e.message }}</span> }
              </label>
              <label class="full"><span class="label-text">Authorisation reference <small>required when the rule says so</small></span>
                <input formControlName="authorisation_ref" autocomplete="off" placeholder="e.g. AUTH-123456" />
                @for (e of fieldErrors('authorisation_ref'); track $index) { <span class="err">{{ e.message }}</span> }
              </label>
            </div>
          </div>
          <div class="pager">
            <span class="key-line" title="Identifies this submission; retries reuse it so nothing is recorded twice">
              Idempotency key <code>{{ idempotencyKey().slice(0, 15) }}…</code>
            </span>
            <div class="group">
              <button type="button" class="secondary" (click)="startNew()">Clear</button>
              <button type="submit" [disabled]="form.invalid || phase() === 'submitting'">
                @if (phase() === 'submitting') { <span class="spinner"></span> Submitting… }
                @else if (phase() === 'failed') { Retry same request }
                @else { Submit dispense }
              </button>
            </div>
          </div>
        </form>

        @if (unplaced().length) {
          <div class="alert bad"><span class="icon">!</span><div>
            @for (e of unplaced(); track $index) { <div>{{ e.message }}</div> }
          </div></div>
        }
        <app-problem-banner [problem]="problem()" />

        @if (accepted(); as d) {
          <div class="alert ok" role="status">
            <span class="icon">✓</span>
            <div>
              <strong>Dispense #{{ d.id }} recorded{{ replayed() ? ' (already processed, original result returned)' : '' }}</strong>
              {{ d.quantity }} × {{ d.medicine_name }} to <span class="mono">{{ d.patient_ref }}</span> at {{ when(d.dispensed_at) }}.
              Business date {{ d.business_date }}, validated against rule #{{ d.formulary_rule_id }}.
              <div style="margin-top:8px"><a [routerLink]="['/patients', d.patient_ref]">Open patient ledger →</a></div>
            </div>
          </div>
        }
      </div>

      <aside class="card aside-card">
        <div class="card-head"><div><h2>Medicine</h2><p>Today's limits, for guidance</p></div></div>
        <div class="card-body">
          @if (medicine(); as m) {
            <div>
              <div class="cell-title">{{ m.name }}</div>
              <div class="med-meta" style="margin-top:6px">
                <span class="code-chip">{{ m.code }}</span>
                @if (m.is_active) { <span class="badge ok">Active</span> } @else { <span class="badge bad">Inactive</span> }
              </div>
            </div>
            @if (m.current_rule; as r) {
              <div class="limit-row"><span>Per dispense</span><strong>{{ r.max_quantity_per_dispense }}</strong></div>
              <div class="limit-row"><span>Per 30 days</span><strong>{{ r.max_quantity_per_30_days }}</strong></div>
              <div class="limit-row"><span>Authorisation</span>
                @if (r.requires_authorisation) { <span class="badge scheduled">Required</span> } @else { <span class="badge ok">Not required</span> }
              </div>
              <p class="hint" style="margin:0">A backdated dispense is judged by the rule in force on its date, which may differ.</p>
            } @else {
              <div class="alert warn" style="margin:0"><span class="icon">!</span><div>No rule in force today.</div></div>
            }
          } @else {
            <p class="hint" style="margin:0">Enter a medicine code to see its current rule.</p>
          }
        </div>
      </aside>
    </div>
  `,
})
export class DispenseCapturePage implements OnInit {
  private readonly api = inject(ApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);

  readonly form = inject(FormBuilder).nonNullable.group({
    medicine_code: ['', [Validators.required, Validators.maxLength(32)]],
    patient_ref: ['', [Validators.required, Validators.maxLength(64)]],
    quantity: [1, [Validators.required, Validators.min(1)]],
    dispensed_at: [nowWallClock(), Validators.required],
    authorisation_ref: ['', Validators.maxLength(64)],
  });

  readonly phase = signal<Phase>('editing');
  readonly idempotencyKey = signal(newKey());
  readonly problem = signal<Problem | null>(null);
  readonly unplaced = signal<ErrorItem[]>([]);
  readonly accepted = signal<Dispense | null>(null);
  readonly replayed = signal(false);
  readonly medicine = signal<MedicineDetail | null>(null);
  readonly when = formatBusinessTime;

  ngOnInit(): void {
    const preset = this.route.snapshot.queryParamMap.get('medicine');
    if (preset) this.form.controls.medicine_code.setValue(preset);

    // After a definitive outcome, the next edit is a new intent -> new key.
    this.form.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => {
      const p = this.phase();
      if (p === 'accepted' || p === 'rejected') {
        this.idempotencyKey.set(newKey());
        this.phase.set('editing');
      }
    });

    // Show the medicine and today's limits as the user types the code.
    this.form.controls.medicine_code.valueChanges
      .pipe(
        map((c) => c.trim()),
        debounceTime(300),
        distinctUntilChanged(),
        switchMap((c) => (c ? this.api.medicine(c).pipe(catchError(() => of(null))) : of(null))),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((m) => this.medicine.set(m));
    if (preset) this.api.medicine(preset).pipe(catchError(() => of(null))).subscribe((m) => this.medicine.set(m));
  }

  fieldErrors(name: string): ErrorItem[] {
    return serverErrors(this.form.get(name));
  }

  submit(): void {
    if (this.form.invalid || this.phase() === 'submitting') return;
    const v = this.form.getRawValue();
    const body: DispenseRequest = {
      medicine_code: v.medicine_code.trim(),
      patient_ref: v.patient_ref.trim(),
      quantity: Number(v.quantity),
      dispensed_at: wallClockToIso(v.dispensed_at),
      authorisation_ref: v.authorisation_ref.trim() || null,
      idempotency_key: this.idempotencyKey(),
    };
    this.phase.set('submitting');
    this.problem.set(null);
    this.unplaced.set([]);
    this.accepted.set(null);

    this.api.dispense(body).subscribe({
      next: (res) => {
        this.accepted.set(res.body);
        this.replayed.set(res.headers.get('Idempotent-Replayed') === 'true');
        this.phase.set('accepted');
      },
      error: (err) => {
        const p = toProblem(err);
        this.problem.set(p);
        if (p.retryable) {
          this.phase.set('failed'); // keep the key: retrying is safe
          return;
        }
        this.unplaced.set(applyServerErrors(this.form, p.errors));
        this.phase.set('rejected');
      },
    });
  }

  startNew(): void {
    this.form.reset({ dispensed_at: nowWallClock(), quantity: 1 });
    this.idempotencyKey.set(newKey());
    this.phase.set('editing');
    this.problem.set(null);
    this.unplaced.set([]);
    this.accepted.set(null);
  }
}

function newKey(): string {
  return `ui-${crypto.randomUUID()}`;
}
