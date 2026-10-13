import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

@Component({
  selector: 'app-root',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  template: `
    <header>
      <strong>Pharmacy formulary</strong>
      <nav>
        <a routerLink="/medicines" routerLinkActive="active">Medicines</a>
        <a routerLink="/dispense" routerLinkActive="active">Capture dispense</a>
        <a routerLink="/patients" routerLinkActive="active">Patient ledger</a>
      </nav>
      <small>Times in Africa/Johannesburg</small>
    </header>
    <main><router-outlet /></main>
  `,
})
export class App {}
