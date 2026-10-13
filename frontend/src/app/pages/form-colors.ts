/** A consistent swatch per dosage form, used in tables and headers. */
const COLORS: Record<string, string> = {
  tablet: '#0d9488',
  capsule: '#6366f1',
  suspension: '#0ea5e9',
  injection: '#e11d48',
  cream: '#f59e0b',
  inhaler: '#8b5cf6',
};

export function formColor(form: string): string {
  return COLORS[form] ?? '#94a3b8';
}
