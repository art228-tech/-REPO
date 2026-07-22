import { Logger } from "../logging/logger.js";
import { sleep } from "../util/sleep.js";
import { AutomationEndpoint, CreateProfileOptions, IDolphinService } from "./types.js";

/**
 * Симулятор Dolphin Anty для dry-run и тестов: имитирует создание/запуск/
 * остановку/удаление профиля без реального приложения и сети.
 */
export class SimulatedDolphinService implements IDolphinService {
  private counter = 0;
  readonly created: string[] = [];
  readonly deleted: string[] = [];
  readonly started: string[] = [];
  readonly stopped: string[] = [];

  constructor(private readonly logger?: Logger) {}

  async authenticate(): Promise<void> {
    this.logger?.info("dolphin.sim", "Симуляция: авторизация в локальном API");
    await sleep(50);
  }

  async createProfile(opts: CreateProfileOptions): Promise<string> {
    await sleep(50);
    const id = `sim-profile-${++this.counter}`;
    this.created.push(id);
    this.logger?.success("dolphin.sim", `Симуляция: профиль создан "${opts.name}"`, {
      profileId: id,
      proxy: `${opts.proxy.host}:${opts.proxy.port}`,
    });
    return id;
  }

  async startProfile(profileId: string, _headless: boolean): Promise<AutomationEndpoint> {
    await sleep(50);
    this.started.push(profileId);
    this.logger?.success("dolphin.sim", `Симуляция: профиль запущен`, { profileId });
    return { port: 0, wsEndpoint: "/devtools/browser/simulated" };
  }

  async stopProfile(profileId: string): Promise<void> {
    await sleep(20);
    this.stopped.push(profileId);
    this.logger?.info("dolphin.sim", `Симуляция: профиль остановлен`, { profileId });
  }

  async deleteProfile(profileId: string): Promise<void> {
    await sleep(20);
    this.deleted.push(profileId);
    this.logger?.success("dolphin.sim", `Симуляция: профиль удалён`, { profileId });
  }
}
