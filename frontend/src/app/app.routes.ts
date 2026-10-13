import { Routes } from '@angular/router';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'medicines' },
  {
    path: 'medicines',
    title: 'Medicines',
    loadComponent: () => import('./pages/medicine-search.page').then((m) => m.MedicineSearchPage),
  },
  {
    path: 'medicines/:code',
    title: 'Medicine',
    loadComponent: () => import('./pages/medicine-detail.page').then((m) => m.MedicineDetailPage),
  },
  {
    path: 'dispense',
    title: 'Capture dispense',
    loadComponent: () => import('./pages/dispense-capture.page').then((m) => m.DispenseCapturePage),
  },
  {
    path: 'patients',
    title: 'Patient ledger',
    loadComponent: () => import('./pages/patient-ledger.page').then((m) => m.PatientLedgerPage),
  },
  {
    path: 'patients/:patientRef',
    title: 'Patient ledger',
    loadComponent: () => import('./pages/patient-ledger.page').then((m) => m.PatientLedgerPage),
  },
  { path: '**', redirectTo: 'medicines' },
];
