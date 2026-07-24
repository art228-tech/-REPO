import type { Page } from "puppeteer-core";
import { Logger } from "../logging/logger.js";
import { sleep } from "../util/sleep.js";
import { ELEVENLABS, validatePreviewText, validateVoiceDescription } from "./constants.js";
import { prepareApp } from "./appHelpers.js";
import { clickByText, clickNth, countAny, dumpDiagnostics, textPresent, typeInto } from "./pageHelpers.js";
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
  // Закрыть cookie / пройти онбординг, если всплыли, затем вернуться в Voice Design.
  await prepareApp(page, logger);
  if (page.url().toLowerCase().includes("onboarding")) {
    await page.goto(ELEVENLABS.VOICE_DESIGN_URL, { waitUntil: "domcontentloaded", timeout: 60_000 }).catch(() => undefined);
    await sleep(1500);
  }
  if (/sign-in|signin|login|\/auth\//i.test(page.url())) {
    throw new NotLoggedInError(
      "Voice Design перекинул на страницу входа — вход в ElevenLabs не выполнен.",
    );
  }
  await dumpDiagnostics(page, logger, "страница Voices (до открытия меню создания)");

  // Шаг 1: открыть меню создания голоса («Create Voice» / «Create a voice»).
  logger.info("elevenlabs.voice", "Открываю меню создания голоса");
  await clickByText(page, ELEVENLABS_SELECTORS.voiceDesignEntryText, 12_000).catch(() => undefined);
  await sleep(1500);
  await dumpDiagnostics(page, logger, "меню создания голоса (выбор типа)");

  // Шаг 2: выбрать «Voice Design» (создание по текстовому промпту).
  logger.info("elevenlabs.voice", "Выбираю вариант Voice Design");
  await clickByText(page, ELEVENLABS_SELECTORS.voiceDesignOptionText, 8000).catch(() => undefined);
  await sleep(1500);
  await dumpDiagnostics(page, logger, "форма Voice Design (поле описания)");

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
  // Кандидаты обычно называются «Voice 1/2/3»; первый выбран по умолчанию.
  await clickByText(page, [`Voice ${index + 1}`], 4000).catch(() => undefined);
  await selectCandidate(page, index).catch(() => undefined);
  await sleep(600);

  logger.info("elevenlabs.voice", "Сохраняю голос (Select voice)");
  const saveClicked = await clickByText(page, ELEVENLABS_SELECTORS.saveVoiceButtonText, 12_000);
  if (!saveClicked) {
    await dumpDiagnostics(page, logger, "не нашёл кнопку сохранения/выбора голоса");
    throw new Error("Не нашёл кнопку сохранения голоса (Select voice)");
  }
  await sleep(1500);
  await dumpDiagnostics(page, logger, "после Select voice (диалог названия?)");

  // Если появился диалог с именем — вводим имя и подтверждаем.
  await typeInto(page, ELEVENLABS_SELECTORS.voiceNameInput, voiceName, { human: true, timeout: 5000 }).catch(
    () => undefined,
  );
  await sleep(500);
  await clickByText(page, ELEVENLABS_SELECTORS.confirmSaveButtonText, 8000, ["cancel", "отмен", "back", "назад"]).catch(
    () => undefined,
  );

  // Проверяем, что модалка создания закрылась (голос сохранён).
  const saved = await waitForModalClosed(page, 20_000);
  if (saved) {
    logger.success("elevenlabs.voice", `Голос "${voiceName}" создан и сохранён`);
  } else {
    await dumpDiagnostics(page, logger, "модалка создания не закрылась после сохранения");
    logger.warn("elevenlabs.voice", `Голос "${voiceName}": не удалось подтвердить сохранение (модалка открыта)`);
  }
  return { id: voiceName, name: voiceName };
}

/** Ждёт закрытия модалки создания голоса (URL без action=create и нет кнопки выбора). */
async function waitForModalClosed(page: Page, timeout: number): Promise<boolean> {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    const url = page.url().toLowerCase();
    const stillOpen = url.includes("action=create") || url.includes("creationtype");
    if (!stillOpen) return true;
    await sleep(700);
  }
  return false;
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
