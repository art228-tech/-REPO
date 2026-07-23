import { GoogleAccount, TtsSettings, VoiceDesignConfig } from "../config/schema.js";
import { AutomationEndpoint } from "../dolphin/types.js";

export interface CreatedVoice {
  id: string;
  name: string;
}

export interface DesignVoiceParams {
  description: string;
  config: VoiceDesignConfig;
  /** Имя, под которым сохранить голос. */
  voiceName: string;
}

export interface SynthesizeParams {
  text: string;
  voice: CreatedVoice;
  settings: TtsSettings;
  /** Полный путь, куда сохранить итоговый аудиофайл. */
  outputPath: string;
}

export interface SynthesizeResult {
  outputPath: string;
  /** Сколько символов ушло (для учёта токенов), если удалось определить. */
  charactersUsed?: number;
  /** Длительность готового аудио в секундах (null — определить не удалось). */
  durationSec?: number | null;
}

/**
 * Абстракция автоматизации ElevenLabs. Есть две реализации:
 * настоящая (Puppeteer + Dolphin) и симулятор (для dry-run/тестов).
 */
/** Параметры входа: ручное подтверждение при капче/2FA. */
export interface LoginOptions {
  /** Разрешить паузу для ручного прохождения reCAPTCHA/2FA в окне браузера. */
  manualAssist: boolean;
  /** Сколько секунд ждать ручного действия. */
  manualAssistTimeoutSec: number;
}

export interface IElevenLabsAutomation {
  /** Подключение к уже запущенному профилю Dolphin по CDP. */
  connect(endpoint: AutomationEndpoint): Promise<void>;
  /** Вход в ElevenLabs через Google-аккаунт. */
  loginWithGoogle(account: GoogleAccount, options?: LoginOptions): Promise<void>;
  /** Остаток кредитов (символов) на аккаунте. */
  getRemainingCredits(): Promise<number>;
  /** Создание голоса через Voice Design. */
  designVoice(params: DesignVoiceParams): Promise<CreatedVoice>;
  /** Синтез речи и скачивание файла. */
  synthesize(params: SynthesizeParams): Promise<SynthesizeResult>;
  /** Завершение работы, отключение от браузера. */
  close(): Promise<void>;
}

/** Ошибка исчерпания кредитов ElevenLabs — сигнал завершить работу. */
export class OutOfCreditsError extends Error {
  constructor(message = "Кредиты ElevenLabs закончились") {
    super(message);
    this.name = "OutOfCreditsError";
  }
}

/** Ошибка отбраковки промпта голоса (например, слишком длинный/короткий). */
export class VoiceDescriptionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "VoiceDescriptionError";
  }
}

/** Вход в ElevenLabs не выполнен (страница перекинула на sign-in). Фатально для запуска. */
export class NotLoggedInError extends Error {
  constructor(message = "Вход в ElevenLabs не выполнен") {
    super(message);
    this.name = "NotLoggedInError";
  }
}
