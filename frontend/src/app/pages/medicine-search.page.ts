import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { debounceTime, distinctUntilChanged, map } from 'rxjs';
import { ApiService } from '../core/api.service';
import { Medicine } from '../core/api.types';
import { CursorPager } from '../core/cursor-pager';
import { formColor } from './form-colors';
import { ProblemBanner } from './problem-banner';

/** View 1. The URL (?q=) is the source of truth, so back/forward and shared links work. */
@Component({
  selector: 'app-medicine-search',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, RouterLink, ProblemBanner],
  template: `
    <div class="page-head">
      <div>
        <h1>Medicines</h1>
        <p>Search the catalogue by name or code. Open a medicine to see its formulary rule history.</p>
      </div>
      <div class="search-box">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
        <input type="search" [formControl]="q" placeholder="Search e.g. zentra or MED000012" aria-label="Search medicines" autofocus />
      </div>
    </div>

    <app-problem-banner [problem]="pager.error()" />

    <div class="card">
      <div class="table-wrap">
        <table [class.busy]="pager.loading()">
          <thead>
            <tr><th>Code</th><th>Medicine</th><th>Form</th><th class="num">Strength</th><th>Status</th></tr>
          </thead>
          <tbody>
            @for (m of pager.items(); track m.code) {
              <tr class="clickable" (click)="open(m.code)">
                <td><a class="code-chip" [routerLink]="['/medicines', m.code]" (click)="$event.stopPropagation()">{{ m.code }}</a></td>
                <td class="cell-title">{{ m.name }}</td>
                <td><span class="form-pill"><i [style.background]="color(m.form)"></i>{{ m.form }}</span></td>
                <td class="num">{{ +m.strength_value }} <span class="hint">{{ m.strength_unit }}</span></td>
                <td>
                  @if (m.is_active) { <span class="badge ok">Active</span> }
                  @else { <span class="badge muted">Inactive</span> }
                </td>
              </tr>
            } @empty {
              @if (!pager.loading()) {
                <tr><td colspan="5" class="empty"><strong>No medicines match "{{ q.value }}"</strong>Try part of a name or a code.</td></tr>
              }
            }
          </tbody>
        </table>
      </div>
      <div class="pager">
        <span>Page {{ pager.pageNumber() }} · {{ pager.items().length }} shown</span>
        <div class="group">
          <button class="secondary" (click)="pager.prev()" [disabled]="!pager.hasPrev() || pager.loading()">← Previous</button>
          <button class="secondary" (click)="pager.next()" [disabled]="!pager.hasNext() || pager.loading()">Next →</button>
        </div>
      </div>
    </div>
  `,
})
export class MedicineSearchPage implements OnInit {
  private readonly api = inject(ApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  readonly q = new FormControl('', { nonNullable: true });
  readonly pager = new CursorPager<Medicine, string>((q, cursor) => this.api.searchMedicines(q, cursor));
  readonly color = formColor;

  open(code: string): void {
    this.router.navigate(['/medicines', code]);
  }

  ngOnInit(): void {
    // URL -> data (and -> input, for back/forward navigation)
    this.route.queryParamMap
      .pipe(
        map((p) => p.get('q') ?? ''),
        distinctUntilChanged(),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((q) => {
        if (this.q.value !== q) this.q.setValue(q, { emitEvent: false });
        this.pager.load(q);
      });

    // input -> URL
    this.q.valueChanges
      .pipe(debounceTime(250), map((v) => v.trim()), distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe((q) =>
        this.router.navigate([], { queryParams: { q: q || null }, replaceUrl: true, queryParamsHandling: 'merge' }),
      );
  }
}
