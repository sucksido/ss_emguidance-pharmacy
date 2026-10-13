import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { Problem } from '../core/api.types';

/** Renders a problem document: title, detail and EVERY item in `errors`. */
@Component({
  selector: 'app-problem-banner',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (problem(); as p) {
      <div class="problem" role="alert">
        <strong>{{ p.title }}</strong>
        @if (p.detail) { <span> — {{ p.detail }}</span> }
        @if (p.errors.length) {
          <ul>
            @for (e of p.errors; track $index) {
              <li>
                <code>{{ e.code }}</code>
                @if (e.field) { <em>({{ e.field }})</em> }
                {{ e.message }}
              </li>
            }
          </ul>
        }
        @if (p.attempt_id) { <small>Attempt #{{ p.attempt_id }} logged.</small> }
      </div>
    }
  `,
})
export class ProblemBanner {
  readonly problem = input<Problem | null>(null);
}
