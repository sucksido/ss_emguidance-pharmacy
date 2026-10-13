import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { BUSINESS_TZ } from './core/sast-time';

const clockFmt = new Intl.DateTimeFormat('en-ZA', {
  timeZone: BUSINESS_TZ,
  weekday: 'short',
  day: '2-digit',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
});

@Component({
  selector: 'app-root',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  template: `
    <header class="topbar">
      <div class="topbar-inner">
        <a class="brand" routerLink="/medicines">
          <span class="brand-mark">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="#fff"><path d="M6 1h4v5h5v4h-5v5H6v-5H1V6h5z"/></svg>
          </span>
          <span>Formulary<small>Community pharmacy</small></span>
        </a>
        <nav class="nav">
          <a routerLink="/medicines" routerLinkActive="active">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m10.5 20.5 10-10a4.95 4.95 0 1 0-7-7l-10 10a4.95 4.95 0 1 0 7 7Z"/><path d="m8.5 8.5 7 7"/></svg>
            <span>Medicines</span>
          </a>
          <a routerLink="/dispense" routerLinkActive="active">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14"/><rect x="3" y="3" width="18" height="18" rx="4"/></svg>
            <span>Capture dispense</span>
          </a>
          <a routerLink="/patients" routerLinkActive="active">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></svg>
            <span>Patient ledger</span>
          </a>
        </nav>
        <div class="clock" title="All business rules are evaluated in Africa/Johannesburg time">
          <strong>{{ now() }}</strong>
          Africa/Johannesburg
        </div>
      </div>
    </header>
    <main><router-outlet /></main>
  `,
})
export class App {
  readonly now = signal(clockFmt.format(new Date()));

  constructor() {
    const id = setInterval(() => this.now.set(clockFmt.format(new Date())), 15_000);
    inject(DestroyRef).onDestroy(() => clearInterval(id));
  }
}
