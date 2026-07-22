import { z } from "zod";
import { parseProxyString } from "../util/proxy.js";

/** Настройки прокси, который добавляется к профилю Dolphin Anty. */
export const proxySchema = z.object({
  type: z.enum(["http", "socks4", "socks5", "ssh"]).default("http"),
  host: z.string().min(1, "Укажите host прокси"),
  port: z.coerce.number().int().min(1).max(65535),
  login: z.string().optional().default(""),
  password: z.string().optional().default(""),
  name: z.string().optional().default(""),
  /** URL для смены IP (rotating-прокси), опционально. */
  changeIpUrl: z.string().optional().default(""),
});
export type ProxyConfig = z.infer<typeof proxySchema>;

/** Данные Google-аккаунта для входа в ElevenLabs. */
export const googleAccountSchema = z.object({
  email: z.string().min(3, "Укажите email от Google-аккаунта"),
  password: z.string().min(1, "Укажите пароль от Google-аккаунта"),
  /** Опциональный секрет для 2FA (TOTP), если включён. */
  totpSecret: z.string().optional().default(""),
  /** Резервный код восстановления, если потребуется. */
  recoveryEmail: z.string().optional().default(""),
});
export type GoogleAccount = z.infer<typeof googleAccountSchema>;

/** Параметры дизайна голоса (Voice Design). */
export const voiceDesignSchema = z.object({
  /** Модель генерации голоса. */
  model: z.enum(["eleven_ttv_v3", "eleven_multilingual_ttv_v2"]).default("eleven_ttv_v3"),
  /** Сколько голосов создать за запуск. */
  voicesToCreate: z.coerce.number().int().min(1).max(10).default(3),
  /**
   * Текст-превью для прослушивания голоса. Если пусто — ElevenLabs
   * сгенерирует превью автоматически. Должен быть 100..1000 символов.
   */
  previewText: z.string().optional().default(""),
  /** Индекс превью-кандидата (0..2), который сохраняем как голос. */
  previewToSaveIndex: z.coerce.number().int().min(0).max(2).default(0),
  /** Префикс имени сохраняемых голосов. */
  voiceNamePrefix: z.string().default("AutoVoice"),
});
export type VoiceDesignConfig = z.infer<typeof voiceDesignSchema>;

/** Настройки синтеза речи (Text to Speech). */
export const ttsSettingsSchema = z.object({
  model: z
    .enum(["eleven_multilingual_v2", "eleven_v3", "eleven_turbo_v2_5", "eleven_flash_v2_5"])
    .default("eleven_multilingual_v2"),
  /** Стабильность 0..1. */
  stability: z.coerce.number().min(0).max(1).default(0.5),
  /** Похожесть 0..1. */
  similarity: z.coerce.number().min(0).max(1).default(0.75),
  /** Выразительность/стиль 0..1. */
  style: z.coerce.number().min(0).max(1).default(0),
  /** Скорость 0.7..1.2. */
  speed: z.coerce.number().min(0.7).max(1.2).default(1.0),
  /** Усиление говорящего (speaker boost). */
  speakerBoost: z.boolean().default(true),
  /** Формат выходного файла. */
  outputFormat: z.enum(["mp3", "wav"]).default("mp3"),
});
export type TtsSettings = z.infer<typeof ttsSettingsSchema>;

/** Полная конфигурация запуска. */
export const appConfigSchema = z.object({
  /** Папка для скачанных озвучек. */
  downloadDir: z.string().min(1, "Выберите папку для скачивания озвучек"),
  /** Папка с промптами для создания голосов. */
  promptsDir: z.string().min(1, "Выберите папку с промптами голосов"),
  /** Папка с текстами для озвучки. */
  textsDir: z.string().min(1, "Выберите папку с текстами для озвучки"),

  proxy: proxySchema,
  /**
   * Прокси одной строкой: host:port:login:password (или host:port,
   * login:pass@host:port, scheme://...). Если задана — разбирается и
   * перекрывает поля proxy при валидации. Хранится, чтобы UI показывал ввод.
   */
  proxyString: z.string().optional().default(""),
  google: googleAccountSchema,
  voiceDesign: voiceDesignSchema,
  tts: ttsSettingsSchema,

  /** API-токен Dolphin Anty (Bearer) для remote API. */
  dolphinApiToken: z.string().min(1, "Укажите API-токен Dolphin Anty"),
  /** Базовый URL локального API Dolphin (по умолчанию http://localhost:3001). */
  dolphinLocalApi: z.string().url().default("http://localhost:3001"),
  /** Базовый URL remote API Dolphin. */
  dolphinRemoteApi: z.string().url().default("https://dolphin-anty-api.com"),
  /** Платформа fingerprint профиля. */
  platform: z.enum(["windows", "macos", "linux"]).default("windows"),
  /** Префикс имени создаваемого профиля. */
  profileNamePrefix: z.string().default("EL-Auto"),

  /** Удалять профиль после завершения работы. */
  deleteProfileOnFinish: z.boolean().default(true),
  /** Удалять текстовые файлы после успешной озвучки. */
  consumeTextFiles: z.boolean().default(true),
  /** Запускать браузер в headless-режиме. */
  headless: z.boolean().default(false),
  /**
   * Порог остатка кредитов, ниже которого прекращаем работу
   * (чтобы не начинать заведомо неуспешную генерацию).
   */
  minCreditsThreshold: z.coerce.number().int().min(0).default(0),

  /**
   * Минимальная длительность готовой озвучки в секундах. Если результат
   * короче — текст отбраковывается и заменяется следующим. 0 = без нижней границы.
   */
  minDurationSec: z.coerce.number().min(0).default(10),
  /**
   * Максимальная длительность готовой озвучки в секундах. Если результат
   * длиннее — текст отбраковывается и заменяется следующим. 0 = без верхней границы.
   */
  maxDurationSec: z.coerce.number().min(0).default(17),
  /** Сухой прогон: без Dolphin/ElevenLabs, на симуляторах (для тестов). */
  dryRun: z.boolean().default(false),
}).refine(
  (c) => c.maxDurationSec === 0 || c.minDurationSec === 0 || c.maxDurationSec >= c.minDurationSec,
  { message: "maxDurationSec должен быть не меньше minDurationSec", path: ["maxDurationSec"] },
);
export type AppConfig = z.infer<typeof appConfigSchema>;

/** Значения по умолчанию для UI (частичная конфигурация). */
export const defaultConfig: Partial<AppConfig> = {
  proxy: { type: "http", host: "", port: 8080, login: "", password: "", name: "", changeIpUrl: "" },
  proxyString: "",
  google: { email: "", password: "", totpSecret: "", recoveryEmail: "" },
  voiceDesign: {
    model: "eleven_ttv_v3",
    voicesToCreate: 3,
    previewText: "",
    previewToSaveIndex: 0,
    voiceNamePrefix: "AutoVoice",
  },
  tts: {
    model: "eleven_multilingual_v2",
    stability: 0.5,
    similarity: 0.75,
    style: 0,
    speed: 1.0,
    speakerBoost: true,
    outputFormat: "mp3",
  },
  dolphinLocalApi: "http://localhost:3001",
  dolphinRemoteApi: "https://dolphin-anty-api.com",
  platform: "windows",
  profileNamePrefix: "EL-Auto",
  deleteProfileOnFinish: true,
  consumeTextFiles: true,
  headless: false,
  minCreditsThreshold: 0,
  minDurationSec: 10,
  maxDurationSec: 17,
  dryRun: false,
};

export interface ValidationResult {
  ok: boolean;
  config?: AppConfig;
  errors?: { path: string; message: string }[];
}

/**
 * Если задана строка proxyString — разбирает её и подставляет в объект proxy
 * (тип берётся из схемы строки, иначе из выбранного в UI, иначе http).
 */
function normalizeInput(input: unknown): unknown {
  if (!input || typeof input !== "object") return input;
  const clone: Record<string, any> = { ...(input as Record<string, any>) };
  const ps = clone.proxyString;
  if (typeof ps === "string" && ps.trim()) {
    const parsed = parseProxyString(ps); // может бросить — ловится в validateConfig
    const prev = (clone.proxy ?? {}) as Record<string, any>;
    clone.proxy = {
      type: parsed.type ?? prev.type ?? "http",
      host: parsed.host,
      port: parsed.port,
      login: parsed.login,
      password: parsed.password,
      name: prev.name ?? "",
      changeIpUrl: prev.changeIpUrl ?? "",
    };
  }
  return clone;
}

/** Валидирует произвольный объект как AppConfig. */
export function validateConfig(input: unknown): ValidationResult {
  let normalized: unknown;
  try {
    normalized = normalizeInput(input);
  } catch (error) {
    return {
      ok: false,
      errors: [{ path: "proxyString", message: error instanceof Error ? error.message : String(error) }],
    };
  }
  const parsed = appConfigSchema.safeParse(normalized);
  if (parsed.success) {
    return { ok: true, config: parsed.data };
  }
  return {
    ok: false,
    errors: parsed.error.issues.map((issue) => ({
      path: issue.path.join("."),
      message: issue.message,
    })),
  };
}
