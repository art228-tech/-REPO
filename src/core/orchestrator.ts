import { EventEmitter } from "node:events";
import fs from "node:fs/promises";
import path from "node:path";
import { AppConfig } from "../config/schema.js";
import { checkDuration } from "../util/audioDuration.js";
import { DolphinService } from "../dolphin/dolphinService.js";
import { SimulatedDolphinService } from "../dolphin/simulated.js";
import { IDolphinService } from "../dolphin/types.js";
import { chunkText } from "../elevenlabs/constants.js";
import { ElevenLabsAutomation } from "../elevenlabs/elevenLabsAutomation.js";
import { SimulatedElevenLabs } from "../elevenlabs/simulated.js";
import { CreatedVoice, IElevenLabsAutomation, NotLoggedInError, OutOfCreditsError, VoiceDescriptionError } from "../elevenlabs/types.js";
import { Logger } from "../logging/logger.js";
import { PromptQueue } from "../queue/promptQueue.js";
import { TextQueue } from "../queue/textQueue.js";
import { sanitizeFilename, uniquePath } from "../util/fsUtils.js";

export type RunState = "idle" | "running" | "stopping" | "done" | "error";

export interface RunStatus {
  state: RunState;
  step: string;
  profileId: string | null;
  voicesCreated: number;
  voicesTarget: number;
  filesDone: number;
  filesFailed: number;
  /** Тексты, отбракованные по длительности (вне диапазона). */
  filesRejected: number;
  textsRemaining: number;
  creditsRemaining: number | null;
  startedAt: number | null;
  finishedAt: number | null;
  error: string | null;
}

export interface OrchestratorDeps {
  dolphin?: IDolphinService;
  elevenlabs?: IElevenLabsAutomation;
}

/**
 * Главный движок сценария. Управляет полным циклом: профиль Dolphin →
 * вход в ElevenLabs → создание голосов → озвучка текстов по кругу голосами →
 * завершение и удаление профиля. Эмитит события `status` для UI.
 */
export class Orchestrator extends EventEmitter {
  private status: RunStatus = Orchestrator.initialStatus();
  private stopRequested = false;
  private running = false;

  constructor(private readonly logger: Logger) {
    super();
  }

  static initialStatus(): RunStatus {
    return {
      state: "idle",
      step: "Ожидание",
      profileId: null,
      voicesCreated: 0,
      voicesTarget: 0,
      filesDone: 0,
      filesFailed: 0,
      filesRejected: 0,
      textsRemaining: 0,
      creditsRemaining: null,
      startedAt: null,
      finishedAt: null,
      error: null,
    };
  }

  getStatus(): RunStatus {
    return { ...this.status };
  }

  isRunning(): boolean {
    return this.running;
  }

  requestStop(): void {
    if (this.running) {
      this.stopRequested = true;
      this.update({ state: "stopping", step: "Останавливаю по запросу пользователя" });
      this.logger.warn("orchestrator", "Получен запрос на остановку");
    }
  }

  private update(patch: Partial<RunStatus>): void {
    this.status = { ...this.status, ...patch };
    this.emit("status", this.getStatus());
  }

  /** Запускает полный сценарий. Возвращает финальный статус. */
  async run(config: AppConfig, deps: OrchestratorDeps = {}): Promise<RunStatus> {
    if (this.running) throw new Error("Сценарий уже выполняется");
    this.running = true;
    this.stopRequested = false;
    this.status = Orchestrator.initialStatus();
    this.update({
      state: "running",
      step: "Инициализация",
      startedAt: Date.now(),
      voicesTarget: config.voiceDesign.voicesToCreate,
    });

    const sessionId = new Date().toISOString().replace(/[:.]/g, "-");
    this.logger.startSession(sessionId);
    this.logger.info("orchestrator", "Старт сценария автоозвучки", {
      dryRun: config.dryRun,
      voicesTarget: config.voiceDesign.voicesToCreate,
    });

    const dolphin = deps.dolphin ?? this.buildDolphin(config);
    const el = deps.elevenlabs ?? this.buildElevenLabs(config);

    let profileId: string | null = null;
    let connected = false;

    try {
      const prompts = new PromptQueue(config.promptsDir);
      const texts = new TextQueue(config.textsDir, config.consumeTextFiles);
      await prompts.load();
      await texts.load();
      this.update({ textsRemaining: texts.remaining });
      this.logger.info("orchestrator", `Промптов: ${prompts.size}, текстов к озвучке: ${texts.remaining}`);
      if (prompts.isEmpty()) throw new Error("Папка промптов пуста");

      this.update({ step: "Авторизация Dolphin" });
      await dolphin.authenticate();

      this.abortIfStopping();
      this.update({ step: "Создание профиля" });
      const profileName = `${config.profileNamePrefix}-${sessionId}`;
      profileId = await dolphin.createProfile({
        name: profileName,
        platform: config.platform,
        proxy: config.proxy,
        mainWebsite: "https://elevenlabs.io",
      });
      this.update({ profileId });

      this.abortIfStopping();
      this.update({ step: "Запуск профиля" });
      const endpoint = await dolphin.startProfile(profileId, config.headless);

      this.update({ step: "Подключение к браузеру" });
      await el.connect(endpoint);
      connected = true;

      this.abortIfStopping();
      this.update({ step: "Вход в ElevenLabs через Google" });
      await el.loginWithGoogle(config.google);

      this.update({ step: "Создание голосов" });
      const voices = await this.createVoices(config, prompts, el);
      if (voices.length === 0) throw new Error("Не удалось создать ни одного голоса");

      this.update({ step: "Озвучка текстов" });
      await this.voiceoverLoop(config, texts, voices, el);

      this.update({ state: this.stopRequested ? "done" : "done", step: "Завершение" });
      this.logger.success("orchestrator", "Сценарий завершён", {
        files: this.status.filesDone,
        failed: this.status.filesFailed,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      if (this.stopRequested) {
        this.update({ state: "done", step: "Остановлено пользователем" });
        this.logger.warn("orchestrator", "Сценарий остановлен пользователем");
      } else {
        this.update({ state: "error", step: "Ошибка", error: message });
        this.logger.error("orchestrator", `Сценарий прерван: ${message}`, { stack: (error as Error)?.stack });
      }
    } finally {
      await this.cleanup(config, dolphin, el, profileId, connected);
      this.update({ finishedAt: Date.now() });
      if (this.status.state !== "error") this.update({ state: "done" });
      this.running = false;
      this.logger.closeSession();
    }
    return this.getStatus();
  }

  private buildDolphin(config: AppConfig): IDolphinService {
    if (config.dryRun) return new SimulatedDolphinService(this.logger);
    return new DolphinService(
      {
        localApiUrl: config.dolphinLocalApi,
        remoteApiUrl: config.dolphinRemoteApi,
        apiToken: config.dolphinApiToken,
      },
      this.logger,
    );
  }

  private buildElevenLabs(config: AppConfig): IElevenLabsAutomation {
    if (config.dryRun) return new SimulatedElevenLabs(this.logger, { initialCredits: 5000 });
    return new ElevenLabsAutomation(this.logger);
  }

  /** Создаёт нужное число голосов, циклически беря промпты. */
  private async createVoices(
    config: AppConfig,
    prompts: PromptQueue,
    el: IElevenLabsAutomation,
  ): Promise<CreatedVoice[]> {
    const target = config.voiceDesign.voicesToCreate;
    const voices: CreatedVoice[] = [];
    // Ограничиваем число попыток, чтобы не зациклиться на плохих промптах.
    const maxAttempts = target + prompts.size + 2;
    let attempts = 0;

    while (voices.length < target && attempts < maxAttempts) {
      this.abortIfStopping();
      attempts += 1;
      const prompt = prompts.next();
      const voiceName = `${config.voiceDesign.voiceNamePrefix}-${voices.length + 1}`;
      try {
        this.update({ step: `Создание голоса ${voices.length + 1}/${target}` });
        const voice = await el.designVoice({
          description: prompt.content,
          config: config.voiceDesign,
          voiceName,
        });
        voices.push(voice);
        this.update({ voicesCreated: voices.length });
      } catch (error) {
        if (error instanceof OutOfCreditsError) throw error;
        if (error instanceof NotLoggedInError) throw error; // фатально — нет смысла пробовать другие промпты
        if (error instanceof VoiceDescriptionError) {
          this.logger.warn("orchestrator", `Промпт "${prompt.name}" отбракован, пробую следующий`, {
            reason: error.message,
          });
          continue;
        }
        this.logger.warn("orchestrator", `Ошибка создания голоса из "${prompt.name}", пробую следующий`, {
          error: error instanceof Error ? error.message : String(error),
        });
      }
    }
    this.logger.info("orchestrator", `Создано голосов: ${voices.length}/${target}`);
    return voices;
  }

  /** Основной цикл озвучки: тексты по одному, голоса по кругу. */
  private async voiceoverLoop(
    config: AppConfig,
    texts: TextQueue,
    voices: CreatedVoice[],
    el: IElevenLabsAutomation,
  ): Promise<void> {
    let voiceIndex = 0;
    while (texts.hasNext()) {
      if (this.stopRequested) {
        this.logger.warn("orchestrator", "Цикл озвучки прерван по запросу остановки");
        break;
      }

      const credits = await el.getRemainingCredits();
      this.update({ creditsRemaining: Number.isFinite(credits) ? credits : null });
      if (credits <= config.minCreditsThreshold) {
        this.logger.warn("orchestrator", `Кредиты (${credits}) достигли порога — завершаю`);
        break;
      }

      const item = texts.next();
      if (!item) break;
      this.update({ textsRemaining: texts.remaining });

      const content = await texts.readContent(item);
      if (content.length === 0) {
        this.logger.warn("orchestrator", `Файл "${item.name}" пуст — пропускаю и удаляю`);
        await texts.complete(item);
        continue;
      }

      // Голос назначаем на слот, но переключаем только после УСПЕШНОЙ,
      // прошедшей по длительности озвучки — чтобы отбракованный текст
      // заменялся следующим на том же голосе.
      const voice = voices[voiceIndex % voices.length];

      try {
        const { paths, totalDurationSec } = await this.synthesizeText(config, item.name, content, voice, el);

        const verdict = checkDuration(totalDurationSec, config.minDurationSec, config.maxDurationSec);
        if (verdict === "too_short" || verdict === "too_long") {
          // Отбраковка по длительности: удаляем результат, текст не берём,
          // заменяем следующим (голос остаётся тем же).
          for (const p of paths) await fs.unlink(p).catch(() => undefined);
          texts.fail(item);
          this.update({ filesRejected: this.status.filesRejected + 1 });
          this.logger.warn("orchestrator", `Текст "${item.name}" отбракован по длительности — заменяю следующим`, {
            durationSec: totalDurationSec,
            allowed: `${config.minDurationSec}-${config.maxDurationSec} c`,
            verdict,
          });
          continue;
        }

        await texts.complete(item);
        voiceIndex += 1;
        this.update({ filesDone: this.status.filesDone + 1 });
      } catch (error) {
        if (error instanceof OutOfCreditsError) {
          this.logger.warn("orchestrator", "Кредиты закончились во время озвучки — завершаю цикл", {
            file: item.name,
          });
          break;
        }
        texts.fail(item);
        this.update({ filesFailed: this.status.filesFailed + 1 });
        this.logger.error("orchestrator", `Не удалось озвучить "${item.name}"`, {
          error: error instanceof Error ? error.message : String(error),
        });
      }
    }
  }

  /**
   * Озвучивает один текст, разбивая на части при превышении лимита.
   * Возвращает пути созданных файлов и суммарную длительность (для проверки
   * попадания в допустимый диапазон секунд).
   */
  private async synthesizeText(
    config: AppConfig,
    fileName: string,
    content: string,
    voice: CreatedVoice,
    el: IElevenLabsAutomation,
  ): Promise<{ paths: string[]; totalDurationSec: number | null }> {
    const ext = config.tts.outputFormat === "wav" ? ".wav" : ".mp3";
    const base = sanitizeFilename(fileName.replace(/\.[^.]+$/, ""));
    const chunks = chunkText(content);

    const paths: string[] = [];
    let totalDuration = 0;
    let anyDurationKnown = false;

    for (let i = 0; i < chunks.length; i++) {
      this.abortIfStopping();
      const suffix = chunks.length > 1 ? `_part${i + 1}` : "";
      const baseName = sanitizeFilename(`${base}__${voice.name}${suffix}`);
      const outputPath = await uniquePath(config.downloadDir, baseName, ext);
      this.logger.info("orchestrator", `Озвучка "${fileName}" голосом "${voice.name}"`, {
        chunk: `${i + 1}/${chunks.length}`,
        chars: chunks[i].length,
      });
      const result = await el.synthesize({ text: chunks[i], voice, settings: config.tts, outputPath });
      paths.push(result.outputPath);
      if (typeof result.durationSec === "number" && Number.isFinite(result.durationSec)) {
        totalDuration += result.durationSec;
        anyDurationKnown = true;
      }
    }

    return { paths, totalDurationSec: anyDurationKnown ? totalDuration : null };
  }

  /** Останавливает и удаляет профиль, отключается от браузера. */
  private async cleanup(
    config: AppConfig,
    dolphin: IDolphinService,
    el: IElevenLabsAutomation,
    profileId: string | null,
    connected: boolean,
  ): Promise<void> {
    this.update({ step: "Завершение и очистка" });
    if (connected) {
      await el.close().catch((e) => this.logger.warn("orchestrator", "Ошибка при закрытии браузера", { error: String(e) }));
    }
    if (profileId) {
      await dolphin
        .stopProfile(profileId)
        .catch((e) => this.logger.warn("orchestrator", "Ошибка остановки профиля", { error: String(e) }));

      // При ошибке профиль НЕ удаляем — оставляем для диагностики.
      const endedWithError = this.status.state === "error";
      if (config.deleteProfileOnFinish && !endedWithError) {
        await dolphin
          .deleteProfile(profileId)
          .catch((e) => this.logger.warn("orchestrator", "Ошибка удаления профиля", { error: String(e) }));
      } else if (endedWithError) {
        this.logger.warn("orchestrator", "Профиль НЕ удалён из-за ошибки — оставлен для диагностики", {
          profileId,
        });
      }
    }
  }

  private abortIfStopping(): void {
    if (this.stopRequested) {
      throw new Error("Остановлено пользователем");
    }
  }
}
