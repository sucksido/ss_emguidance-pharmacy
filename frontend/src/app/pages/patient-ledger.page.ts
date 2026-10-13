import { ChangeDetectionStrategy, Component, effect, inject, input } from '@angular/core';
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
    <h1>Patient ledger</h1>
    <form (ngSubmit)="open()" class="inline">
      <label>Patient reference <input [formControl]="ref" placeholder="PT-R000001" /></label>
      <button type="submit" [disabled]="!ref.value.trim()">Show dispenses</button>
    </form>

    @if (patientRef()) {
      <h2>{{ patientRef() }}</h2>
      <app-problem-banner [problem]="pager.error()" />
      <table [class.busy]="pager.loading()">
        <thead>
          <tr><th>Dispensed (SAST)</th><th>Medicine</th><th>Qty</th><th>Authorisation</th><th>Rule</th><th>#</th></tr>
        </thead>
        <tbody>
          @for (d of pager.items(); track d.id) {
            <tr>
              <td>{{ when(d.dispensed_at) }}</td>
              <td><a [routerLink]="['/medicines', d.medicine_code]">{{ d.medicine_code }}</a> {{ d.medicine_name }}</td>
              <td>{{ d.quantity }}</td>
              <td>{{ d.authorisation_ref ?? '—' }}</td>
              <td>#{{ d.formulary_rule_id }}</td>
              <td>{{ d.id }}</td>
            </tr>
          } @empty {
            @if (!pager.loading()) { <tr><td colspan="6" class="empty">No dispenses for this patient.</td></tr> }
          }
        </tbody>
      </table>
      <nav class="pager">
        <button (click)="pager.prev()" [disabled]="!pager.hasPrev() || pager.loading()">← Newer</button>
        <span>Page {{ pager.pageNumber() }}</span>
        <button (click)="pager.next()" [disabled]="!pager.hasNext() || pager.loading()">Older →</button>
      </nav>
    }
  `,
})
export class PatientLedgerPage {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);

  readonly patientRef = input<string>('');
  readonly ref = new FormControl('', { nonNullable: true });
  readonly when = formatBusinessTime;
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
