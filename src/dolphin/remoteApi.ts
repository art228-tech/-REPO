import { Logger } from "../logging/logger.js";
import { describeError, fetchWithTimeout, NetworkError } from "../util/net.js";
import { DolphinHttpError } from "./httpError.js";
import { CreateProfileOptions } from "./types.js";

const DEFAULT_USER_AGENTS: Record<string, string> = {
  windows:
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
  macos:
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
  linux:
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
};

const OS_VERSION: Record<string, string> = { windows: "10", macos: "13", linux: "" };

/**
 * Клиент облачного (remote) API Dolphin Anty: создание/удаление профилей,
 * создание прокси. Требует Bearer-токен.
 */
export class DolphinRemoteApi {
  constructor(
    private readonly baseUrl: string,
    private readonly token: string,
    private readonly logger: Logger,
  ) {}

  private async request<T = any>(method: string, path: string, body?: unknown, timeoutMs = 20_000): Promise<T> {
    const url = `${this.baseUrl}${path}`;
    let res: Response;
    try {
      res = await fetchWithTimeout(
        url,
        {
          method,
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${this.token}`,
          },
          body: body === undefined ? undefined : JSON.stringify(body),
        },
        timeoutMs,
      );
    } catch (error) {
      const detail = describeError(error);
      this.logger.error("dolphin.remote", `Сеть: не удалось соединиться с ${this.baseUrl}`, {
        method,
        path,
        detail,
      });
      throw new NetworkError(`Нет соединения с ${this.baseUrl} — ${detail}`, error);
    }
    const text = await res.text();
    if (!res.ok) {
      this.logger.error("dolphin.remote", `HTTP ${res.status} ${method} ${path}`, {
        status: res.status,
        body: text.slice(0, 1000),
      });
      throw new DolphinHttpError(`Dolphin remote API ${res.status}`, res.status, text, url);
    }
    return (text ? JSON.parse(text) : {}) as T;
  }

  /** Пытается получить рекомендованный User-Agent, иначе возвращает дефолт. */
  async fetchUserAgent(platform: string): Promise<string> {
    try {
      const res = await this.request<any>(
        "GET",
        `/useragent?browser_type=anty&platform=${encodeURIComponent(platform)}`,
        undefined,
        8000,
      );
      const ua = res?.data?.[0]?.value ?? res?.data?.value ?? res?.value;
      if (typeof ua === "string" && ua.includes("Mozilla")) return ua;
    } catch (error) {
      this.logger.debug("dolphin.remote", "Не удалось получить UA из API, использую дефолт", {
        error: String(error),
      });
    }
    return DEFAULT_USER_AGENTS[platform] ?? DEFAULT_USER_AGENTS.windows;
  }

  /** Формирует payload профиля из документированного шаблона Dolphin Anty. */
  buildProfilePayload(opts: CreateProfileOptions, userAgent: string): Record<string, unknown> {
    const proxy = opts.proxy;
    return {
      name: opts.name,
      platform: opts.platform,
      browserType: "anty",
      mainWebsite: opts.mainWebsite ?? "",
      useragent: { mode: "manual", value: userAgent },
      webrtc: { mode: "altered", ipAddress: null },
      canvas: { mode: "real" },
      webgl: { mode: "real" },
      webglInfo: { mode: "off" },
      timezone: { mode: "auto", value: null },
      locale: { mode: "auto", value: null },
      geolocation: { mode: "auto" },
      cpu: { mode: "manual", value: 4 },
      memory: { mode: "manual", value: 8 },
      screen: { mode: "real", resolution: null },
      doNotTrack: false,
      osVersion: OS_VERSION[opts.platform] ?? "10",
      proxy: {
        type: proxy.type,
        host: proxy.host,
        port: Number(proxy.port),
        login: proxy.login || undefined,
        password: proxy.password || undefined,
        name: proxy.name || `${opts.name}-proxy`,
        changeIpUrl: proxy.changeIpUrl || undefined,
      },
    };
  }

  /** Создаёт профиль, возвращает его id (строкой). */
  async createProfile(opts: CreateProfileOptions): Promise<string> {
    const userAgent = await this.fetchUserAgent(opts.platform);
    const payload = this.buildProfilePayload(opts, userAgent);
    const res = await this.request<any>("POST", "/browser_profiles", payload);
    const id =
      res?.browserProfileId ??
      res?.data?.id ??
      res?.data?.browserProfileId ??
      res?.id ??
      res?.data?.data?.id;
    if (id === undefined || id === null) {
      throw new Error(`Не удалось извлечь id профиля из ответа Dolphin: ${JSON.stringify(res).slice(0, 500)}`);
    }
    return String(id);
  }

  /** Удаляет профиль по id. Отсутствующий профиль (404) считается удалённым. */
  async deleteProfile(profileId: string): Promise<void> {
    try {
      await this.request("DELETE", `/browser_profiles/${encodeURIComponent(profileId)}`);
    } catch (error) {
      if (error instanceof DolphinHttpError && error.status === 404) {
        this.logger.debug("dolphin.remote", "Профиль уже отсутствует (404) — считаю удалённым", { profileId });
        return;
      }
      throw error;
    }
  }
}
