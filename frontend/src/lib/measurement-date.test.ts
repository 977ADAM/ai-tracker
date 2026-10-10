import { expect, it } from 'vitest';
import { measurementDate, measurementFreshness } from './measurement-date';
it('uses Moscow calendar dates across UTC midnight', () => {
  expect(measurementFreshness('2026-10-09T22:30:00Z', new Date('2026-10-10T12:00:00Z'))).toBe(
    'Сегодня',
  );
  expect(measurementFreshness('2026-10-09T20:30:00Z', new Date('2026-10-10T12:00:00Z'))).toBe(
    'Вчера',
  );
  expect(measurementFreshness('2026-10-07T12:00:00Z', new Date('2026-10-10T12:00:00Z'))).toBe(
    '3 дня назад',
  );
  expect(measurementFreshness('2026-09-29T12:00:00Z', new Date('2026-10-10T12:00:00Z'))).toBe(
    '11 дней назад',
  );
});
it('handles invalid dates and keeps future timestamps explicit', () => {
  expect(measurementDate('bad')).toBe('Дата неизвестна');
  expect(measurementFreshness('2026-10-11T12:00:00Z', new Date('2026-10-10T12:00:00Z'))).toBe(
    '11.10.2026 15:00',
  );
});
