/** Ошибка HTTP-запроса к API Dolphin Anty с сохранением тела ответа. */
export class DolphinHttpError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly body: string,
    readonly url: string,
  ) {
    super(message);
    this.name = "DolphinHttpError";
  }
}

/** Признак того, что ошибку имеет смысл повторить (сеть/5xx/429). */
export function isRetriableHttp(error: unknown): boolean {
  if (error instanceof DolphinHttpError) {
    return error.status >= 500 || error.status === 429;
  }
  // Сетевые ошибки fetch (ECONNREFUSED, таймауты и т.п.)
  return true;
}
