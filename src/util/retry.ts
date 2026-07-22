import { sleep } from "./sleep.js";

export interface RetryOptions {
  /** Максимальное число попыток (включая первую). */
  attempts?: number;
  /** Начальная задержка перед повтором, мс. */
  baseDelayMs?: number;
  /** Максимальная задержка между повторами, мс. */
  maxDelayMs?: number;
  /** Множитель экспоненциального роста задержки. */
  factor?: number;
  /** Колбэк, вызываемый перед каждым повтором. */
  onRetry?: (error: unknown, attempt: number, nextDelayMs: number) => void;
  /** Позволяет прервать повторы для некоторых ошибок (вернуть false — не повторять). */
  shouldRetry?: (error: unknown) => boolean;
}

/**
 * Выполняет асинхронную операцию с экспоненциальным бэкоффом.
 * Бросает последнюю ошибку, если все попытки исчерпаны.
 */
export async function retry<T>(fn: (attempt: number) => Promise<T>, options: RetryOptions = {}): Promise<T> {
  const attempts = options.attempts ?? 4;
  const baseDelayMs = options.baseDelayMs ?? 1000;
  const maxDelayMs = options.maxDelayMs ?? 30_000;
  const factor = options.factor ?? 2;

  let lastError: unknown;
  for (let attempt = 1; attempt <= attempts; attempt++) {
    try {
      return await fn(attempt);
    } catch (error) {
      lastError = error;
      if (options.shouldRetry && !options.shouldRetry(error)) {
        throw error;
      }
      if (attempt >= attempts) break;
      const delay = Math.min(maxDelayMs, baseDelayMs * Math.pow(factor, attempt - 1));
      options.onRetry?.(error, attempt, delay);
      await sleep(delay);
    }
  }
  throw lastError;
}
