import { HttpErrorResponse } from '@angular/common/http';
import { AbstractControl, FormGroup } from '@angular/forms';
import { ErrorItem, Problem } from './api.types';

/**
 * Normalises any HTTP failure into the API's problem shape, so components only
 * ever deal with one error model. Network failures and non-problem bodies
 * (e.g. a proxy's HTML 502) become synthetic problems with `retryable: true`.
 */
export function toProblem(err: unknown): Problem & { retryable: boolean } {
  if (err instanceof HttpErrorResponse && isProblem(err.error)) {
    return { ...err.error, retryable: err.status >= 500 };
  }
  const status = err instanceof HttpErrorResponse ? err.status : 0;
  return {
    type: 'about:blank',
    title: status === 0 ? 'Could not reach the server' : `Unexpected response (${status})`,
    status,
    code: status === 0 ? 'NETWORK_ERROR' : 'UNEXPECTED_RESPONSE',
    detail: 'Your request may or may not have been processed. Retrying is safe.',
    instance: '',
    errors: [],
    retryable: true,
  };
}

function isProblem(body: unknown): body is Problem {
  return !!body && typeof body === 'object' && 'code' in body && Array.isArray((body as Problem).errors);
}

/**
 * Attaches each server error to the form control named by its `field`.
 * Returns the errors that could not be attached (field null or unknown), which
 * the caller shows at form level. Nothing is dropped.
 */
export function applyServerErrors(form: FormGroup, errors: ErrorItem[]): ErrorItem[] {
  const unplaced: ErrorItem[] = [];
  const byControl = new Map<AbstractControl, ErrorItem[]>();
  for (const e of errors) {
    const control = e.field ? form.get(e.field) : null;
    if (!control) {
      unplaced.push(e);
      continue;
    }
    byControl.set(control, [...(byControl.get(control) ?? []), e]);
  }
  for (const [control, items] of byControl) {
    control.setErrors({ ...(control.errors ?? {}), server: items });
    control.markAsTouched();
  }
  return unplaced;
}

export function serverErrors(control: AbstractControl | null): ErrorItem[] {
  return (control?.errors?.['server'] as ErrorItem[] | undefined) ?? [];
}
