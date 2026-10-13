import { DestroyRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Observable, Subject, catchError, of, switchMap, tap } from 'rxjs';
import { Page, Problem } from './api.types';
import { toProblem } from './problem';

interface Request<F> {
  filters: F;
  cursor: string | null;
}

/**
 * Signal-based state for a keyset-paginated listing.
 *
 * - The API only moves forward (next_cursor). "Previous" is supported by keeping
 *   the stack of cursors that led to the current page.
 * - Every load goes through switchMap, so a slow response for an old query can
 *   never overwrite the result of a newer one (typing fast in a search box).
 * - Changing filters resets the stack: a cursor is only valid for the filters
 *   that produced it (the API enforces this too).
 */
export class CursorPager<T, F> {
  private readonly requests = new Subject<Request<F>>();
  private readonly stack = signal<(string | null)[]>([null]);
  private filters: F | null = null;

  readonly items = signal<T[]>([]);
  readonly loading = signal(false);
  readonly error = signal<Problem | null>(null);
  readonly nextCursor = signal<string | null>(null);
  readonly pageNumber = computed(() => this.stack().length);
  readonly hasPrev = computed(() => this.stack().length > 1);
  readonly hasNext = computed(() => this.nextCursor() !== null);

  constructor(fetch: (filters: F, cursor: string | null) => Observable<Page<T>>) {
    this.requests
      .pipe(
        tap(() => {
          this.loading.set(true);
          this.error.set(null);
        }),
        switchMap(({ filters, cursor }) =>
          fetch(filters, cursor).pipe(
            catchError((e) => {
              this.error.set(toProblem(e));
              return of(null);
            }),
          ),
        ),
        takeUntilDestroyed(inject(DestroyRef)),
      )
      .subscribe((page) => {
        this.loading.set(false);
        if (!page) return;
        this.items.set(page.items);
        this.nextCursor.set(page.page.next_cursor);
      });
  }

  load(filters: F): void {
    this.filters = filters;
    this.stack.set([null]);
    this.requests.next({ filters, cursor: null });
  }

  next(): void {
    const cursor = this.nextCursor();
    if (!cursor || this.filters === null) return;
    this.stack.update((s) => [...s, cursor]);
    this.requests.next({ filters: this.filters, cursor });
  }

  prev(): void {
    if (!this.hasPrev() || this.filters === null) return;
    this.stack.update((s) => s.slice(0, -1));
    const s = this.stack();
    this.requests.next({ filters: this.filters, cursor: s[s.length - 1] });
  }
}
