/** Russian count forms, including 11–14. */
export function countLabel(count: number, one: string, few: string, many: string): string {
  const n = Math.abs(count) % 100;
  const last = n % 10;
  const word = n >= 11 && n <= 14 ? many : last === 1 ? one : last >= 2 && last <= 4 ? few : many;
  return `${count} ${word}`;
}
