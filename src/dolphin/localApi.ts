import { Logger } from "../logging/logger.js";
import { DolphinHttpError } from "./httpError.js";
import { AutomationEndpoint } from "./types.js";

/**
 * Клиент локального API Dolphin Anty (по умолчанию http://localhost:3001).
 * Работает только при запущенном десктоп-приложении Dolphin{anty}.
 */
export class DolphinLocalApi {
  constructor(private readonly baseUrl: string, private readonly logger: Logger) {}

  private async request<T = any>(method: string, path: string, body?: unknown): Promise<T> {
    const url = `${this.baseUrl}${path}`;
    const res = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const text = await res.text();
    if (!res.ok) {
      this.logger.error("dolphin.local", `HTTP ${res.status} ${method} ${path}`, {
        status: res.status,
        body: text.slice(0, 1000),
      });
      throw new DolphinHttpError(`Dolphin local API ${res.status}`, res.status, text, url);
    }
    return (text ? JSON.parse(text) : {}) as T;
  }

  /** Авторизация в локальном API токеном (иначе start вернёт 401). */
  async loginWithToken(token: string): Promise<void> {
    await this.request("POST", "/v1.0/auth/login-with-token", { token });
    this.logger.info("dolphin.local", "Локальный API авторизован по токену");
  }

  /** Запускает профиль с автоматизацией и возвращает port + wsEndpoint. */
  async startProfile(profileId: string, headless: boolean): Promise<AutomationEndpoint> {
    const query = `automation=1${headless ? "&headless=1" : ""}`;
    const res = await this.request<any>(
      "GET",
      `/v1.0/browser_profiles/${encodeURIComponent(profileId)}/start?${query}`,
    );
    const automation = res?.automation ?? res;
    const port = Number(automation?.port);
    const wsEndpoint: string = automation?.wsEndpoint ?? "";
    if (!port || !wsEndpoint) {
      throw new Error(`Профиль запущен, но нет port/wsEndpoint: ${JSON.stringify(res).slice(0, 500)}`);
    }
    return { port, wsEndpoint };
  }

  /** Останавливает профиль. */
  async stopProfile(profileId: string): Promise<void> {
    await this.request("GET", `/v1.0/browser_profiles/${encodeURIComponent(profileId)}/stop`);
  }
}
