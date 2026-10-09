export async function projectRequest<T>(
  path: string,
  method = 'GET',
  payload?: unknown,
): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: payload === undefined ? undefined : { 'content-type': 'application/json' },
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
  if (response.status === 204) return undefined as T;
  const value = await response.json();
  if (!response.ok)
    throw new Error(
      typeof value.detail === 'string' ? value.detail : 'Не удалось выполнить запрос',
    );
  return value as T;
}
export const percent = (value: number | null) =>
  value == null ? '—' : Math.round(value * 100) + '%';
export const sentimentLabels: Record<string, string> = {
  positive: 'Положительная',
  neutral: 'Нейтральная',
  negative: 'Отрицательная',
  unknown: 'Не определена',
};
export const measurementLabels: Record<string, string> = {
  running: 'Выполняется',
  completed: 'Завершён',
  failed: 'Ошибка',
  cancelled: 'Отменён',
  interrupted: 'Прерван',
};
