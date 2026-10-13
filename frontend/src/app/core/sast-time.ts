/**
 * The UI captures and displays times in Africa/Johannesburg regardless of the
 * browser's own time zone, mirroring the API's rule that business logic is
 * evaluated in that zone. The wire format is always ISO-8601 with an explicit
 * offset, so the server never has to guess.
 */
export const BUSINESS_TZ = 'Africa/Johannesburg';

/** Offset of BUSINESS_TZ at a given instant, as "+02:00". Computed, not hard-coded. */
export function businessOffset(at: Date = new Date()): string {
  const part = new Intl.DateTimeFormat('en-US', { timeZone: BUSINESS_TZ, timeZoneName: 'longOffset' })
    .formatToParts(at)
    .find((p) => p.type === 'timeZoneName')?.value; // e.g. "GMT+02:00"
  const m = part?.match(/GMT([+-]\d{2}:\d{2})/);
  return m ? m[1] : '+00:00';
}

/** "2026-06-15T09:30" (wall-clock in Johannesburg) -> "2026-06-15T09:30:00+02:00". */
export function wallClockToIso(local: string): string {
  const withSeconds = local.length === 16 ? `${local}:00` : local;
  const approx = new Date(`${withSeconds}Z`); // offset lookup only needs the right day
  return `${withSeconds}${businessOffset(approx)}`;
}

/** Current Johannesburg wall-clock time in <input type="datetime-local"> format. */
export function nowWallClock(now: Date = new Date()): string {
  const p = Object.fromEntries(
    new Intl.DateTimeFormat('en-CA', {
      timeZone: BUSINESS_TZ,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    })
      .formatToParts(now)
      .map((x) => [x.type, x.value]),
  );
  return `${p['year']}-${p['month']}-${p['day']}T${p['hour']}:${p['minute']}`;
}

const display = new Intl.DateTimeFormat('en-ZA', {
  timeZone: BUSINESS_TZ,
  dateStyle: 'medium',
  timeStyle: 'short',
});

export function formatBusinessTime(iso: string): string {
  return display.format(new Date(iso));
}
