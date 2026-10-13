import { describe, expect, it } from 'vitest';
import { businessOffset, formatBusinessTime, nowWallClock, wallClockToIso } from './sast-time';

describe('Africa/Johannesburg time helpers', () => {
  it('derives the +02:00 offset from the zone database', () => {
    expect(businessOffset(new Date('2026-01-15T12:00:00Z'))).toBe('+02:00');
    expect(businessOffset(new Date('2026-07-15T12:00:00Z'))).toBe('+02:00');
  });

  it('turns a wall-clock input into an ISO string with explicit offset', () => {
    expect(wallClockToIso('2026-06-15T09:30')).toBe('2026-06-15T09:30:00+02:00');
  });

  it('reads "now" as Johannesburg wall-clock, not browser-local', () => {
    // 22:30Z on 31 March is already 1 April in Johannesburg.
    expect(nowWallClock(new Date('2026-03-31T22:30:00Z'))).toBe('2026-04-01T00:30');
  });

  it('formats instants in Johannesburg time', () => {
    expect(formatBusinessTime('2026-03-31T22:30:00Z')).toContain('00:30');
  });
});
