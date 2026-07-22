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
}

/**
 * Абстракция автоматизации ElevenLabs. Есть две реализации:
 * настоящая (Puppeteer + Dolphin) и симулятор (для dry-run/тестов).
 */
export interface IElevenLabsAutomation {
  /** Подключение к уже запущенному профилю Dolphin по CDP. */
  connect(endpoint: AutomationEndpoint): Promise<void>;
  /** Вход в ElevenLabs через Google-аккаунт. */
  loginWithGoogle(account: GoogleAccount): Promise<void>;
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
