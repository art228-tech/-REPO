import path from "node:path";
import type { Page } from "puppeteer-core";
import { Logger } from "../logging/logger.js";
import { sleep } from "../util/sleep.js";
import { getAudioDurationSec } from "../util/audioDuration.js";
import { ELEVENLABS } from "./constants.js";
import { enableDownloads, moveDownload, snapshotDir, waitForNewDownload } from "./download.js";
import { clickByText, textPresent, typeInto, waitForAny } from "./pageHelpers.js";
import { ELEVENLABS_SELECTORS } from "./selectors.js";
import { OutOfCreditsError, SynthesizeParams, SynthesizeResult } from "./types.js";

/**
 * Синтезирует речь из текста выбранным голосом и скачивает результат.
 * Обрабатывает исчерпание кредитов (бросает OutOfCreditsError).
 */
export async function synthesize(page: Page, params: SynthesizeParams, logger: Logger): Promise<SynthesizeResult> {
  const { text, voice, outputPath } = params;
  const downloadDir = path.dirname(outputPath);

  logger.info("elevenlabs.tts", `Открываю Text to Speech, голос "${voice.name}"`);
  await page.goto(ELEVENLABS.TTS_URL, { waitUntil: "domcontentloaded", timeout: 60_000 });
  await sleep(1500);

  await selectVoice(page, voice.name, logger);

  const typed = await typeInto(page, ELEVENLABS_SELECTORS.ttsTextarea, text, { delay: 3 });
  if (!typed) {
    throw new Error("Не нашёл поле ввода текста в Text to Speech");
  }
  await sleep(500);

  if (await textPresent(page, ELEVENLABS_SELECTORS.outOfCreditsText)) {
    throw new OutOfCreditsError("TTS: обнаружено сообщение об исчерпании кредитов до генерации");
  }

  await enableDownloads(page, downloadDir);
  const before = await snapshotDir(downloadDir);

  logger.info("elevenlabs.tts", "Запускаю генерацию речи");
  const generated = await clickByText(page, ELEVENLABS_SELECTORS.generateSpeechButtonText, 15_000);
  if (!generated) {
    throw new Error("Не нашёл кнопку генерации речи");
  }

  // Ждём завершения генерации / появления ошибки кредитов.
  await waitForGenerationDone(page, 180_000, logger);
  if (await textPresent(page, ELEVENLABS_SELECTORS.outOfCreditsText)) {
    throw new OutOfCreditsError("TTS: кредиты закончились во время генерации");
  }

  logger.info("elevenlabs.tts", "Скачиваю аудио");
  const downloadClicked = await clickByText(page, ELEVENLABS_SELECTORS.downloadButtonText, 20_000);
  if (!downloadClicked) {
    throw new Error("Не нашёл кнопку скачивания аудио");
  }

  const downloaded = await waitForNewDownload(downloadDir, before, 120_000);
  if (downloaded !== outputPath) {
    await moveDownload(downloaded, outputPath);
  }
  const durationSec = await getAudioDurationSec(outputPath, logger);
  logger.success("elevenlabs.tts", `Аудио сохранено`, { outputPath, durationSec });
  return { outputPath, charactersUsed: text.length, durationSec };
}

/** Открывает селектор голосов, ищет по имени и выбирает. */
async function selectVoice(page: Page, voiceName: string, logger: Logger): Promise<void> {
  const opened =
    (await clickByText(page, [voiceName], 3000)) ||
    (await (async () => {
      for (const sel of ELEVENLABS_SELECTORS.voiceSelector) {
        const el = await page.$(sel).catch(() => null);
        if (el) {
          await el.click().catch(() => undefined);
          return true;
        }
      }
      return false;
    })());
  if (!opened) {
    logger.warn("elevenlabs.tts", "Не удалось открыть селектор голоса — использую текущий выбранный");
    return;
  }
  await sleep(600);
  // Поиск голоса по имени в выпадающем списке.
  const searchTyped = await typeInto(page, ['input[type="search"]', 'input[placeholder*="search" i]'], voiceName, {
    delay: 20,
  }).catch(() => false);
  if (searchTyped) await sleep(600);
  await clickByText(page, [voiceName], 6000).catch(() => undefined);
}

/** Ожидает завершения генерации: появление кнопки скачивания или плеера. */
async function waitForGenerationDone(page: Page, timeout: number, logger: Logger): Promise<void> {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    if (await textPresent(page, ELEVENLABS_SELECTORS.outOfCreditsText)) return;
    const downloadBtn = await waitForAny(
      page,
      ['button[aria-label*="download" i]', 'a[download]', 'button:has(svg)'],
      1500,
    ).catch(() => null);
    const hasDownloadText = await textPresent(page, ELEVENLABS_SELECTORS.downloadButtonText);
    if (downloadBtn && hasDownloadText) return;
    await sleep(1000);
  }
  logger.warn("elevenlabs.tts", "Таймаут ожидания завершения генерации — пробую скачать как есть");
}
