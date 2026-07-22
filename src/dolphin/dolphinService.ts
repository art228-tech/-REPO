import { Logger } from "../logging/logger.js";
import { retry } from "../util/retry.js";
import { isRetriableHttp } from "./httpError.js";
import { DolphinLocalApi } from "./localApi.js";
import { DolphinRemoteApi } from "./remoteApi.js";
import { AutomationEndpoint, CreateProfileOptions, IDolphinService } from "./types.js";

export interface DolphinServiceOptions {
  localApiUrl: string;
  remoteApiUrl: string;
  apiToken: string;
}

/**
 * Высокоуровневый сервис поверх локального и remote API Dolphin Anty.
 * Все сетевые операции обёрнуты в ретраи с экспоненциальным бэкоффом.
 */
export class DolphinService implements IDolphinService {
  private readonly local: DolphinLocalApi;
  private readonly remote: DolphinRemoteApi;

  constructor(private readonly options: DolphinServiceOptions, private readonly logger: Logger) {
    this.local = new DolphinLocalApi(options.localApiUrl, logger);
    this.remote = new DolphinRemoteApi(options.remoteApiUrl, options.apiToken, logger);
  }

  private retryOpts(action: string) {
    return {
      attempts: 4,
      baseDelayMs: 2000,
      shouldRetry: isRetriableHttp,
      onRetry: (error: unknown, attempt: number, next: number) =>
        this.logger.warn("dolphin", `Повтор ${action} (попытка ${attempt})`, {
          error: String(error),
          nextDelayMs: next,
        }),
    };
  }

  async authenticate(): Promise<void> {
    await retry(() => this.local.loginWithToken(this.options.apiToken), this.retryOpts("авторизации"));
  }

  async createProfile(opts: CreateProfileOptions): Promise<string> {
    this.logger.info("dolphin", `Создаю профиль "${opts.name}" с прокси ${opts.proxy.host}:${opts.proxy.port}`);
    const id = await retry(() => this.remote.createProfile(opts), this.retryOpts("создания профиля"));
    this.logger.success("dolphin", `Профиль создан`, { profileId: id });
    return id;
  }

  async startProfile(profileId: string, headless: boolean): Promise<AutomationEndpoint> {
    this.logger.info("dolphin", `Запускаю профиль ${profileId} (headless=${headless})`);
    const endpoint = await retry(
      () => this.local.startProfile(profileId, headless),
      this.retryOpts("запуска профиля"),
    );
    this.logger.success("dolphin", `Профиль запущен`, { profileId, port: endpoint.port });
    return endpoint;
  }

  async stopProfile(profileId: string): Promise<void> {
    this.logger.info("dolphin", `Останавливаю профиль ${profileId}`);
    await retry(() => this.local.stopProfile(profileId), this.retryOpts("остановки профиля"));
  }

  async deleteProfile(profileId: string): Promise<void> {
    this.logger.info("dolphin", `Удаляю профиль ${profileId}`);
    await retry(() => this.remote.deleteProfile(profileId), this.retryOpts("удаления профиля"));
    this.logger.success("dolphin", `Профиль удалён`, { profileId });
  }
}
