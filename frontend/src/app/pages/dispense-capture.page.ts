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
    <h1>Capture dispense</h1>
    <form [formGroup]="form" (ngSubmit)="submit()" class="grid" novalidate>
      <label>Medicine code
        <input formControlName="medicine_code" placeholder="MED000001" autocomplete="off" />
        @if (medicine(); as m) {
          <span class="hint">{{ m.name }}
            @if (!m.is_active) { — <strong>inactive</strong> }
            @if (m.current_rule; as r) {
              — today: max {{ r.max_quantity_per_dispense }}/dispense, {{ r.max_quantity_per_30_days }}/30 days{{ r.requires_authorisation ? ', authorisation required' : '' }}
            }
          </span>
        }
        @for (e of fieldErrors('medicine_code'); track $index) { <span class="err">{{ e.message }}</span> }
      </label>

      <label>Patient reference
        <input formControlName="patient_ref" placeholder="PT-0000001" autocomplete="off" />
        @for (e of fieldErrors('patient_ref'); track $index) { <span class="err">{{ e.message }}</span> }
      </label>

      <label>Quantity
        <input type="number" min="1" step="1" formControlName="quantity" />
        @for (e of fieldErrors('quantity'); track $index) { <span class="err">{{ e.message }}</span> }
      </label>

      <label>Dispensed at <small>(Africa/Johannesburg time; may be backdated)</small>
        <input type="datetime-local" formControlName="dispensed_at" />
        @for (e of fieldErrors('dispensed_at'); track $index) { <span class="err">{{ e.message }}</span> }
      </label>

      <label>Authorisation reference <small>(if the rule requires one)</small>
        <input formControlName="authorisation_ref" autocomplete="off" />
        @for (e of fieldErrors('authorisation_ref'); track $index) { <span class="err">{{ e.message }}</span> }
      </label>

      <div class="actions">
        <button type="submit" [disabled]="form.invalid || phase() === 'submitting'">
          {{ phase() === 'submitting' ? 'Submitting…' : phase() === 'failed' ? 'Retry (same request)' : 'Submit dispense' }}
        </button>
        <button type="button" class="secondary" (click)="startNew()">New dispense</button>
        <small class="muted">Idempotency key: <code>{{ idempotencyKey() }}</code></small>
      </div>
    </form>

    @if (unplaced().length) {
      <div class="problem">
        @for (e of unplaced(); track $index) { <div>{{ e.message }}</div> }
      </div>
    }
    <app-problem-banner [problem]="problem()" />

    @if (accepted(); as d) {
      <div class="ok-msg" role="status">
        Dispense #{{ d.id }} recorded{{ replayed() ? ' (replayed — this request had already been processed)' : '' }}:
        {{ d.quantity }} × {{ d.medicine_name }} to {{ d.patient_ref }} at {{ when(d.dispensed_at) }}
        (business date {{ d.business_date }}, rule #{{ d.formulary_rule_id }}).
        <a [routerLink]="['/patients', d.patient_ref]">View patient ledger</a>
      </div>
    }
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
