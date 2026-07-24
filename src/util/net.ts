import dns from "node:dns";

/**
 * Предпочитать IPv4 при резолвинге DNS. Частая причина «fetch failed» на
 * Windows — попытка соединиться по IPv6, который не работает в сети. Это
 * заставляет Node сначала пробовать IPv4.
 */
export function preferIPv4(): void {
  try {
    dns.setDefaultResultOrder("ipv4first");
  } catch {
    // старые версии Node без этого API — не критично
  }
}

/** fetch с таймаутом через AbortController (по умолчанию 20 сек). */
export async function fetchWithTimeout(
  url: string,
  init: RequestInit = {},
  timeoutMs = 20_000,
): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Человекочитаемое описание ошибки сети/fetch, включая реальную причину
 * (error.cause.code, напр. ENOTFOUND, ETIMEDOUT, ECONNREFUSED, ECONNRESET).
 */
export function describeError(error: unknown): string {
  if (error instanceof Error) {
    const cause = (error as { cause?: unknown }).cause as
      | { code?: string; message?: string; errors?: Array<{ code?: string }> }
      | undefined;
    if (error.name === "AbortError") return "таймаут запроса";
    if (cause) {
      const code = cause.code || cause.errors?.[0]?.code || cause.message;
      return code ? `${error.message} (${code})` : error.message;
    }
    return error.message;
  }
  return String(error);
}

/** Сетевая ошибка соединения (в отличие от HTTP-статуса). Повторяемая. */
export class NetworkError extends Error {
  constructor(message: string, readonly cause?: unknown) {
    super(message);
    this.name = "NetworkError";
  }
}
