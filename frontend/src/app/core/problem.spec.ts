import { HttpErrorResponse } from '@angular/common/http';
import { FormControl, FormGroup } from '@angular/forms';
import { describe, expect, it } from 'vitest';
import { ErrorItem } from './api.types';
import { applyServerErrors, serverErrors, toProblem } from './problem';

const item = (code: string, field: string | null): ErrorItem => ({ code, field, message: code, rule_id: null, meta: {} });

describe('applyServerErrors', () => {
  it('attaches every error to its field and returns the unplaceable ones', () => {
    const form = new FormGroup({ quantity: new FormControl(5), authorisation_ref: new FormControl('') });
    const unplaced = applyServerErrors(form, [
      item('MAX_QUANTITY_PER_DISPENSE_EXCEEDED', 'quantity'),
      item('MAX_QUANTITY_PER_30_DAYS_EXCEEDED', 'quantity'),
      item('AUTHORISATION_REQUIRED', 'authorisation_ref'),
      item('SOMETHING_GLOBAL', null),
      item('UNKNOWN_FIELD', 'nope'),
    ]);
    expect(serverErrors(form.get('quantity')).map((e) => e.code)).toEqual([
      'MAX_QUANTITY_PER_DISPENSE_EXCEEDED',
      'MAX_QUANTITY_PER_30_DAYS_EXCEEDED',
    ]);
    expect(serverErrors(form.get('authorisation_ref'))).toHaveLength(1);
    expect(unplaced.map((e) => e.code)).toEqual(['SOMETHING_GLOBAL', 'UNKNOWN_FIELD']);
    expect(form.get('quantity')!.touched).toBe(true);
  });

  it('server errors clear when the user edits the field', () => {
    const form = new FormGroup({ quantity: new FormControl(5) });
    applyServerErrors(form, [item('X', 'quantity')]);
    form.get('quantity')!.setValue(4);
    expect(serverErrors(form.get('quantity'))).toEqual([]);
  });
});

describe('toProblem', () => {
  it('passes API problems through, marking 4xx as not retryable', () => {
    const body = { type: 't', title: 'Dispense rejected', status: 422, code: 'DISPENSE_REJECTED', detail: null, instance: '/', errors: [] };
    const p = toProblem(new HttpErrorResponse({ status: 422, error: body }));
    expect(p.code).toBe('DISPENSE_REJECTED');
    expect(p.retryable).toBe(false);
  });

  it('turns network failures into a retryable synthetic problem', () => {
    const p = toProblem(new HttpErrorResponse({ status: 0, error: new ProgressEvent('error') }));
    expect(p.code).toBe('NETWORK_ERROR');
    expect(p.retryable).toBe(true);
  });

  it('treats a non-problem 502 from a proxy as retryable', () => {
    const p = toProblem(new HttpErrorResponse({ status: 502, error: '<html>Bad gateway</html>' }));
    expect(p.retryable).toBe(true);
  });
});
