import fs from "node:fs/promises";
import path from "node:path";
import { GoogleAccount } from "../config/schema.js";
import { AutomationEndpoint } from "../dolphin/types.js";
import { Logger } from "../logging/logger.js";
import { ensureDir } from "../util/fsUtils.js";
import { sleep } from "../util/sleep.js";
import { validateVoiceDescription } from "./constants.js";
import {
  CreatedVoice,
  DesignVoiceParams,
  IElevenLabsAutomation,
  OutOfCreditsError,
  SynthesizeParams,
  SynthesizeResult,
  VoiceDescriptionError,
} from "./types.js";

export interface SimulatedOptions {
  /** Начальный бюджет кредитов (символов). */
  initialCredits?: number;
  /** Искусственная задержка операций, мс. */
  latencyMs?: number;
  /**
   * Средняя скорость речи (символов в секунду) для расчёта псевдо-длительности
   * синтеза. Позволяет тестам управлять попаданием в диапазон 10–17 сек.
   */
  charsPerSecond?: number;
}

/**
 * Симулятор ElevenLabs. Ведёт учёт кредитов, создаёт файлы-заглушки для
 * озвучки и бросает OutOfCreditsError при исчерпании бюджета. Позволяет
 * прогнать весь сценарий без реального аккаунта и токенов.
 */
export class SimulatedElevenLabs implements IElevenLabsAutomation {
  private credits: number;
  private readonly latency: number;
  private readonly charsPerSecond: number;
  readonly designedVoices: CreatedVoice[] = [];
  readonly synthesized: string[] = [];

  constructor(private readonly logger?: Logger, options: SimulatedOptions = {}) {
    this.credits = options.initialCredits ?? 10_000;
    this.latency = options.latencyMs ?? 30;
    this.charsPerSecond = options.charsPerSecond ?? 15;
  }

  async connect(_endpoint: AutomationEndpoint): Promise<void> {
    await sleep(this.latency);
    this.logger?.info("elevenlabs.sim", "Симуляция: подключение к браузеру");
  }

  async loginWithGoogle(account: GoogleAccount): Promise<void> {
    await sleep(this.latency);
    this.logger?.success("elevenlabs.sim", "Симуляция: вход через Google", { email: account.email });
  }

  async getRemainingCredits(): Promise<number> {
    await sleep(this.latency);
    return this.credits;
  }

  async designVoice(params: DesignVoiceParams): Promise<CreatedVoice> {
    await sleep(this.latency);
    const desc = validateVoiceDescription(params.description);
    if (!desc.ok) {
      throw new VoiceDescriptionError(desc.reason ?? "Некорректное описание голоса (симуляция)");
    }
    const voice: CreatedVoice = { id: params.voiceName, name: params.voiceName };
    this.designedVoices.push(voice);
    this.logger?.success("elevenlabs.sim", `Симуляция: создан голос "${voice.name}"`, {
      truncated: desc.truncated,
    });
    return voice;
  }

  async synthesize(params: SynthesizeParams): Promise<SynthesizeResult> {
    await sleep(this.latency);
    const cost = params.text.length;
    if (this.credits < cost) {
      throw new OutOfCreditsError(`Симуляция: недостаточно кредитов (нужно ${cost}, есть ${this.credits})`);
    }
    this.credits -= cost;
    const durationSec = cost / this.charsPerSecond;
    await ensureDir(path.dirname(params.outputPath));
    await fs.writeFile(
      params.outputPath,
      `SIMULATED AUDIO\nvoice=${params.voice.name}\nchars=${cost}\nduration=${durationSec.toFixed(2)}s\n`,
      "utf8",
    );
    this.synthesized.push(params.outputPath);
    this.logger?.success("elevenlabs.sim", `Симуляция: озвучка сохранена`, {
      outputPath: params.outputPath,
      voice: params.voice.name,
      durationSec: Number(durationSec.toFixed(2)),
      creditsLeft: this.credits,
    });
    return { outputPath: params.outputPath, charactersUsed: cost, durationSec };
  }

  async close(): Promise<void> {
    await sleep(this.latency);
    this.logger?.info("elevenlabs.sim", "Симуляция: закрытие");
  }
}
