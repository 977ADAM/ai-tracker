import { countLabel } from './count';
const zone = 'Europe/Moscow';
export function measurementDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? 'Дата неизвестна'
    : new Intl.DateTimeFormat('ru-RU', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        timeZone: zone,
      })
        .format(date)
        .replace(',', '');
}
function calendarDay(date: Date) {
  const parts = new Intl.DateTimeFormat('en', {
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    timeZone: zone,
  }).formatToParts(date);
  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value);
  return Date.UTC(get('year'), get('month') - 1, get('day')) / 86400000;
}
export function measurementFreshness(value: string, now: Date) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Дата неизвестна';
  const days = calendarDay(now) - calendarDay(date);
  if (days < 0) return measurementDate(value);
  if (days === 0) return 'Сегодня';
  if (days === 1) return 'Вчера';
  return `${countLabel(days, 'день', 'дня', 'дней')} назад`;
}
