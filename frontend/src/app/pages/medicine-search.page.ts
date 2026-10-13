import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { debounceTime, distinctUntilChanged, map } from 'rxjs';
import { ApiService } from '../core/api.service';
import { Medicine } from '../core/api.types';
import { CursorPager } from '../core/cursor-pager';
import { ProblemBanner } from './problem-banner';

/** View 1. The URL (?q=) is the source of truth, so back/forward and shared links work. */
@Component({
  selector: 'app-medicine-search',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, RouterLink, ProblemBanner],
  template: `
    <h1>Medicines</h1>
    <label class="search">
      Search by name or code
      <input type="search" [formControl]="q" placeholder="e.g. zentra, MED00012" autofocus />
    </label>

    <app-problem-banner [problem]="pager.error()" />

    <table [class.busy]="pager.loading()">
      <thead>
        <tr><th>Code</th><th>Name</th><th>Form</th><th>Strength</th><th>Status</th></tr>
      </thead>
      <tbody>
        @for (m of pager.items(); track m.code) {
          <tr>
            <td><a [routerLink]="['/medicines', m.code]">{{ m.code }}</a></td>
            <td>{{ m.name }}</td>
            <td>{{ m.form }}</td>
            <td>{{ +m.strength_value }} {{ m.strength_unit }}</td>
            <td>
              @if (m.is_active) { <span class="chip ok">active</span> }
              @else { <span class="chip muted">inactive</span> }
            </td>
          </tr>
        } @empty {
          @if (!pager.loading()) { <tr><td colspan="5" class="empty">No medicines match.</td></tr> }
        }
      </tbody>
    </table>

    <nav class="pager">
      <button (click)="pager.prev()" [disabled]="!pager.hasPrev() || pager.loading()">← Previous</button>
      <span>Page {{ pager.pageNumber() }}</span>
      <button (click)="pager.next()" [disabled]="!pager.hasNext() || pager.loading()">Next →</button>
    </nav>
  `,
})
export class MedicineSearchPage implements OnInit {
  private readonly api = inject(ApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  readonly q = new FormControl('', { nonNullable: true });
  readonly pager = new CursorPager<Medicine, string>((q, cursor) => this.api.searchMedicines(q, cursor));

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
