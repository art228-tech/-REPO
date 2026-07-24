import { ProxyConfig } from "../config/schema.js";

/** Данные запуска профиля с включённой автоматизацией. */
export interface AutomationEndpoint {
  port: number;
  wsEndpoint: string;
}

export interface CreateProfileOptions {
  name: string;
  platform: "windows" | "macos" | "linux";
  proxy: ProxyConfig;
  /** Стартовый сайт профиля. */
  mainWebsite?: string;
}

/** Высокоуровневый интерфейс работы с Dolphin Anty (для реального клиента и симулятора). */
export interface IDolphinService {
  /** Авторизация в локальном API токеном (нужна для запуска профилей). */
  authenticate(): Promise<void>;
  /** Создаёт профиль с прокси, возвращает его id. */
  createProfile(opts: CreateProfileOptions): Promise<string>;
  /** Запускает профиль с автоматизацией и возвращает CDP-эндпоинт. */
  startProfile(profileId: string, headless: boolean): Promise<AutomationEndpoint>;
  /** Останавливает профиль. */
  stopProfile(profileId: string): Promise<void>;
  /** Удаляет профиль. */
  deleteProfile(profileId: string): Promise<void>;
}
