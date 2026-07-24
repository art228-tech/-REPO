import type { Page } from "puppeteer-core";
import { Logger } from "../logging/logger.js";
import { sleep } from "../util/sleep.js";
import { ELEVENLABS } from "./constants.js";
import { clickByText, clickSelector } from "./pageHelpers.js";
import { ELEVENLABS_SELECTORS } from "./selectors.js";

function safeUrl(page: Page): string {
  try {
    return page.url();
  } catch {
    return "";
  }
}

/** Закрывает баннер cookie (Cookiebot и общие варианты), если он есть. */
export async function dismissCookies(page: Page, logger?: Logger): Promise<void> {
  const bySelector = await clickSelector(page, ELEVENLABS_SELECTORS.cookieAcceptSelectors, 2500).catch(() => false);
  const byText = bySelector ? false : await clickByText(page, ELEVENLABS_SELECTORS.cookieAcceptText, 2500).catch(() => false);
  if (bySelector || byText) {
    logger?.info("elevenlabs.app", "Закрыт баннер cookie");
    await sleep(600);
  }
}

/**
 * Проходит онбординг ElevenLabs («Choose your platform» и последующие шаги):
 * закрывает cookie, при наличии выбирает ElevenCreative и жмёт Continue/Next/
 * Skip, пока не уйдём со страницы /app/onboarding. Идемпотентно и безопасно.
 */
export async function completeOnboarding(page: Page, logger?: Logger): Promise<void> {
  await dismissCookies(page, logger);
  for (let step = 0; step < 8; step++) {
    const url = safeUrl(page).toLowerCase();
    if (!url.includes("onboarding")) return;

    logger?.info("elevenlabs.app", `Онбординг: шаг ${step + 1}`, { url });
    await dismissCookies(page, logger); // баннер может перекрывать кнопки

    // Выбрать платформу (обычно ElevenCreative уже выбрана по умолчанию).
    await clickByText(page, ELEVENLABS_SELECTORS.onboardingPlatformText, 2000).catch(() => undefined);
    await sleep(400);

    const advanced = await clickByText(page, ELEVENLABS_SELECTORS.onboardingContinueText, 5000).catch(() => false);
    await sleep(2500);

    if (!advanced) {
      // Кнопки перехода не нашли — пробуем уйти на домашнюю страницу приложения.
      await page.goto(ELEVENLABS.APP_URL, { waitUntil: "domcontentloaded", timeout: 60_000 }).catch(() => undefined);
      await sleep(2000);
      if (!safeUrl(page).toLowerCase().includes("onboarding")) return;
    }
  }
  logger?.warn("elevenlabs.app", "Онбординг не завершился за отведённые шаги — продолжаю как есть");
}

/** Готовит приложение к работе: cookie + онбординг. */
export async function prepareApp(page: Page, logger?: Logger): Promise<void> {
  await dismissCookies(page, logger);
  if (safeUrl(page).toLowerCase().includes("onboarding")) {
    await completeOnboarding(page, logger);
  }
}
