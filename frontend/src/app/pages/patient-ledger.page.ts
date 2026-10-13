import { ChangeDetectionStrategy, Component, computed, effect, inject, input } from '@angular/core';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { ApiService } from '../core/api.service';
import { Dispense } from '../core/api.types';
import { CursorPager } from '../core/cursor-pager';
import { formatBusinessTime } from '../core/sast-time';
import { ProblemBanner } from './problem-banner';

/** View 4. /patients/:patientRef — the route is the state. */
@Component({
  selector: 'app-patient-ledger',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, RouterLink, ProblemBanner],
  template: `
    <div class="page-head">
      <div>
        <h1>Patient ledger</h1>
        <p>Every dispense for a patient reference, newest first by when it happened.</p>
      </div>
      <form (ngSubmit)="open()" class="inline-form">
        <div class="search-box" style="min-width:300px">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
          <input [formControl]="ref" placeholder="Patient reference, e.g. PT-R000001" aria-label="Patient reference" class="mono" />
        </div>
        <button type="submit" [disabled]="!ref.value.trim()">Show</button>
      </form>
    </div>

    @if (patientRef()) {
      <app-problem-banner [problem]="pager.error()" />
      <div class="card">
        <div class="card-head">
          <div class="patient-chip">
            <span class="avatar">{{ initials() }}</span>
            <div><h2 class="mono">{{ patientRef() }}</h2><p>Opaque patient reference · no personal data stored</p></div>
          </div>
        </div>
        <div class="table-wrap">
          <table [class.busy]="pager.loading()">
            <thead>
              <tr><th>Dispensed (SAST)</th><th>Medicine</th><th class="num">Qty</th><th>Authorisation</th><th>Rule</th><th class="num">#</th></tr>
            </thead>
            <tbody>
              @for (d of pager.items(); track d.id) {
                <tr>
                  <td><div class="cell-title">{{ d.business_date }}</div><div class="cell-sub">{{ when(d.dispensed_at) }}</div></td>
                  <td><div class="cell-title">{{ d.medicine_name }}</div>
                    <a class="cell-sub mono" [routerLink]="['/medicines', d.medicine_code]">{{ d.medicine_code }}</a></td>
                  <td class="num cell-title">{{ d.quantity }}</td>
                  <td>@if (d.authorisation_ref) { <span class="mono">{{ d.authorisation_ref }}</span> } @else { <span class="hint">—</span> }</td>
                  <td><span class="badge plain">#{{ d.formulary_rule_id }}</span></td>
                  <td class="num hint">{{ d.id }}</td>
                </tr>
              } @empty {
                @if (!pager.loading()) { <tr><td colspan="6" class="empty"><strong>No dispenses</strong>Nothing has been dispensed to this patient reference.</td></tr> }
              }
            </tbody>
          </table>
        </div>
        <div class="pager">
          <span>Page {{ pager.pageNumber() }}</span>
          <div class="group">
            <button class="secondary" (click)="pager.prev()" [disabled]="!pager.hasPrev() || pager.loading()">← Newer</button>
            <button class="secondary" (click)="pager.next()" [disabled]="!pager.hasNext() || pager.loading()">Older →</button>
          </div>
        </div>
      </div>
    } @else {
      <div class="card"><div class="empty"><strong>Look up a patient</strong>Enter a patient reference above, or open one from a recorded dispense.</div></div>
    }
  `,
})
export class PatientLedgerPage {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);

  readonly patientRef = input<string>('');
  readonly ref = new FormControl('', { nonNullable: true });
  readonly when = formatBusinessTime;
  readonly initials = computed(() => (this.patientRef() ?? '').replace(/[^A-Za-z0-9]/g, '').slice(-2).toUpperCase());
  readonly pager = new CursorPager<Dispense, string>((patient_ref, cursor) =>
    this.api.dispenses({ patient_ref }, cursor),
  );

  constructor() {
    effect(() => {
      const ref = this.patientRef();
      this.ref.setValue(ref ?? '', { emitEvent: false });
      if (ref) this.pager.load(ref);
    });
  }

  open(): void {
    const ref = this.ref.value.trim();
    if (ref) this.router.navigate(['/patients', ref]);
  }
}
