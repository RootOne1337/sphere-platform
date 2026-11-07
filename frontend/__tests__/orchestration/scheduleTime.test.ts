import { isoToUtcDateTimeInput, utcDateTimeInputToIso } from '@/src/features/orchestration/scheduleTime';

test.each([
  ['2026-10-20T13:45:26.123+05:00', '2026-10-20T08:45:26.123'],
  ['2026-10-20T13:45:26.123-07:00', '2026-10-20T20:45:26.123'],
  ['2026-10-20T23:59:59.999Z', '2026-10-20T23:59:59.999'],
])('normalizes an aware instant %s for the UTC editor without losing milliseconds', (iso, input) => {
  expect(isoToUtcDateTimeInput(iso)).toBe(input);
  expect(new Date(utcDateTimeInputToIso(input)).getTime()).toBe(new Date(iso).getTime());
});

test.each(['2026-10-25T02:30', '2026-03-29T02:30:45.1'])('does not apply local DST rules to explicitly UTC input %s', value => {
  expect(utcDateTimeInputToIso(value)).toBe(value.length === 16 ? `${value}:00.000Z` : '2026-03-29T02:30:45.100Z');
});

test.each(['', '2026-02-30T10:00', '2026-10-20T25:00', '2026-10-20T10:00Z', '2026-10-20T10:00:12.1234', 'not-a-date'])('rejects an invalid datetime-local input %s', value => {
  expect(() => utcDateTimeInputToIso(value)).toThrow();
});

test.each(['2026-10-20T10:00', 'not-a-dateZ'])('rejects an unowned or malformed API instant %s', value => {
  expect(() => isoToUtcDateTimeInput(value)).toThrow();
});
