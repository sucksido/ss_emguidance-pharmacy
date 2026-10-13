import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { Problem } from '../core/api.types';

/** Renders a problem document: title, detail and EVERY item in `errors`. */
@Component({
  selector: 'app-problem-banner',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (problem(); as p) {
      <div class="alert bad" role="alert">
        <span class="icon">!</span>
        <div>
          <strong>{{ p.title }}</strong>
          @if (p.detail) { <span>{{ p.detail }}</span> }
          @if (p.errors.length) {
            <ul>
              @for (e of p.errors; track $index) {
                <li>
                  <code>{{ e.code }}</code>
                  <span>{{ e.message }}</span>
                  @if (e.field) { <span class="hint">· field: {{ e.field }}</span> }
                </li>
              }
            </ul>
          }
          @if (p.attempt_id) { <small>Logged as attempt #{{ p.attempt_id }}. No dispense was recorded.</small> }
        </div>
      </div>
    }
  `,
})
export class ProblemBanner {
  readonly problem = input<Problem | null>(null);
}
