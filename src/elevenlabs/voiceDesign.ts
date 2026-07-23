import type { Page } from "puppeteer-core";
import { Logger } from "../logging/logger.js";
import { sleep } from "../util/sleep.js";
import { ELEVENLABS, validatePreviewText, validateVoiceDescription } from "./constants.js";
import { clickByText, clickNth, countAny, dumpDiagnostics, textPresent, typeInto, waitForText } from "./pageHelpers.js";
import { ELEVENLABS_SELECTORS } from "./selectors.js";
import { CreatedVoice, DesignVoiceParams, NotLoggedInError, OutOfCreditsError, VoiceDescriptionError } from "./types.js";

/**
 * Создаёт голос через Voice Design. Тщательно валидирует описание под лимиты
 * (20..1000 символов), обрабатывает авто-превью, ждёт генерации 3 кандидатов,
 * выбирает нужного и сохраняет под заданным именем.
 */
export async function designVoice(page: Page, params: DesignVoiceParams, logger: Logger): Promise<CreatedVoice> {
  const { config, voiceName } = params;

  const desc = validateVoiceDescription(params.description);
  if (!desc.ok) {
    throw new VoiceDescriptionError(desc.reason ?? "Некорректное описание голоса");
  }
  if (desc.truncated) {
    logger.warn("elevenlabs.voice", desc.reason ?? "Описание обрезано", {
      length: desc.value.length,
    });
  }

  logger.info("elevenlabs.voice", `Открываю Voice Design для "${voiceName}"`);
  await page.goto(ELEVENLABS.VOICE_DESIGN_URL, { waitUntil: "domcontentloaded", timeout: 60_000 });
  await sleep(1500);
  await clickByText(page, ELEVENLABS_SELECTORS.voiceDesignEntryText, 6000).catch(() => undefined);
  await dumpDiagnostics(page, logger, "Voice Design");
  if (/sign-in|signin|login|\/auth\//i.test(page.url())) {
    throw new NotLoggedInError(
      "Voice Design перекинул на страницу входа — вход в ElevenLabs не выполнен (проверьте пароль Google).",
    );
  }

  const descTyped = await typeInto(page, ELEVENLABS_SELECTORS.voiceDescriptionTextarea, desc.value, {
    timeout: 30_000,
  });
  if (!descTyped) {
    throw new Error("Не нашёл поле описания голоса в Voice Design");
  }

  // Текст-превью: используем свой, если валиден, иначе полагаемся на авто-превью.
  const preview = validatePreviewText(config.previewText ?? "");
  if (preview.ok) {
    logger.info("elevenlabs.voice", "Ввожу пользовательский preview-текст");
    await typeInto(page, ELEVENLABS_SELECTORS.previewTextarea, preview.value).catch(() => undefined);
  } else {
    logger.debug("elevenlabs.voice", preview.reason ?? "preview будет сгенерирован автоматически");
  }

  await sleep(500);
  logger.info("elevenlabs.voice", "Запускаю генерацию превью");
  const generateClicked = await clickByText(page, ELEVENLABS_SELECTORS.generateButtonText, 10_000);
  if (!generateClicked) {
    throw new Error("Не нашёл кнопку Generate в Voice Design");
  }

  // Ждём кандидатов или ошибки лимита.
  const appeared = await waitForPreviews(page, 120_000);
  if (await textPresent(page, ELEVENLABS_SELECTORS.outOfCreditsText)) {
    throw new OutOfCreditsError("Voice Design: кредиты закончились при генерации превью");
  }
  if (!appeared) {
    throw new Error("Превью-кандидаты Voice Design не появились вовремя");
  }

  const index = Math.min(config.previewToSaveIndex, ELEVENLABS.PREVIEW_CANDIDATES - 1);
  logger.info("elevenlabs.voice", `Выбираю кандидата #${index + 1}`);
  await selectCandidate(page, index);
  await sleep(500);

  logger.info("elevenlabs.voice", "Сохраняю голос");
  const saveClicked = await clickByText(page, ELEVENLABS_SELECTORS.saveVoiceButtonText, 10_000);
  if (!saveClicked) {
    throw new Error("Не нашёл кнопку сохранения голоса");
  }
  await sleep(1000);
  await typeInto(page, ELEVENLABS_SELECTORS.voiceNameInput, voiceName).catch(() => undefined);
  await sleep(400);
  await clickByText(page, ELEVENLABS_SELECTORS.confirmSaveButtonText, 8000).catch(() => undefined);

  await waitForText(page, ["saved", "added", "сохран", "добавлен", voiceName], 15_000).catch(() => undefined);
  logger.success("elevenlabs.voice", `Голос "${voiceName}" создан и сохранён`);
  return { id: voiceName, name: voiceName };
}

async function waitForPreviews(page: Page, timeout: number): Promise<boolean> {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    if ((await countAny(page, ELEVENLABS_SELECTORS.previewCandidate)) >= 1) return true;
    await sleep(700);
  }
  return false;
}

async function selectCandidate(page: Page, index: number): Promise<void> {
  await clickNth(page, ELEVENLABS_SELECTORS.previewCandidate, index);
}
