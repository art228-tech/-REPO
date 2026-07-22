import type { Browser, Page } from "puppeteer-core";
import { GoogleAccount } from "../config/schema.js";
import { Logger } from "../logging/logger.js";
import { sleep } from "../util/sleep.js";
import { ELEVENLABS } from "./constants.js";
import { clickByText, clickSelector, typeInto, waitForAny, waitForText } from "./pageHelpers.js";
import { ELEVENLABS_SELECTORS, GOOGLE_SELECTORS } from "./selectors.js";
import { generateTotp } from "./totp.js";

/**
 * Выполняет вход в ElevenLabs через Google. Обрабатывает как всплывающее окно
 * Google (popup), так и редирект в том же табе, а также шаг 2FA (TOTP).
 */
export async function loginWithGoogle(
  browser: Browser,
  page: Page,
  account: GoogleAccount,
  logger: Logger,
): Promise<void> {
  logger.info("elevenlabs.login", "Открываю страницу входа ElevenLabs");
  await page.goto(ELEVENLABS.SIGN_IN_URL, { waitUntil: "domcontentloaded", timeout: 60_000 });
  await sleep(1500);

  // Уже залогинены?
  if (await isLoggedIn(page)) {
    logger.success("elevenlabs.login", "Уже выполнен вход, пропускаю авторизацию");
    return;
  }

  const clickedText = await clickByText(page, ELEVENLABS_SELECTORS.googleSignInText, 10_000);
  const clicked = clickedText || (await clickSelector(page, ELEVENLABS_SELECTORS.googleSignInButton, 5000));
  if (!clicked) {
    throw new Error("Не нашёл кнопку входа через Google на странице ElevenLabs");
  }

  // Вход Google может открыться в отдельном окне (popup) или тем же табом
  // (редирект). Надёжно находим нужную страницу по адресу accounts.google.com.
  const googlePage = await findGoogleAuthPage(browser, page, 25_000, logger);
  if (!googlePage) {
    throw new Error(
      "После клика по «Continue with Google» не открылось окно входа Google (popup/редирект не обнаружен)",
    );
  }
  const isPopup = googlePage !== page;
  logger.info("elevenlabs.login", `Открыто окно входа Google`, { url: safeUrl(googlePage), popup: isPopup });
  await sleep(1000);

  await performGoogleAuth(googlePage, account, logger);

  // Если был popup — дождаться его закрытия; иначе вернуться в приложение.
  if (isPopup) {
    const closeStart = Date.now();
    while (!googlePage.isClosed() && Date.now() - closeStart < 30_000) {
      await sleep(500);
    }
  }

  logger.info("elevenlabs.login", "Ожидаю завершения входа в приложение");
  const ok = await waitForLogin(page, 60_000);
  if (!ok) {
    throw new Error("Вход выполнен, но приложение ElevenLabs не подтвердило авторизацию вовремя");
  }
  logger.success("elevenlabs.login", "Успешный вход в ElevenLabs через Google");
}

/** URL страницы без падения, если контекст уже закрыт. */
function safeUrl(page: Page): string {
  try {
    return page.url();
  } catch {
    return "";
  }
}

/** Признак страницы аутентификации Google. */
function isGoogleAuthUrl(url: string): boolean {
  return /accounts\.google\.|\/signin\/|oauth2|\/gsi\/|myaccount\.google\./i.test(url);
}

/**
 * Находит страницу входа Google среди всех вкладок браузера (popup) или
 * определяет редирект в том же табе. Периодически опрашивает список вкладок.
 */
async function findGoogleAuthPage(
  browser: Browser,
  originalPage: Page,
  timeout: number,
  logger: Logger,
): Promise<Page | null> {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    if (isGoogleAuthUrl(safeUrl(originalPage))) return originalPage;
    const pages = await browser.pages().catch(() => [] as Page[]);
    for (const p of pages) {
      if (p.isClosed?.()) continue;
      if (isGoogleAuthUrl(safeUrl(p))) {
        await p.bringToFront().catch(() => undefined);
        return p;
      }
    }
    await sleep(500);
  }
  logger.warn("elevenlabs.login", "Окно входа Google не найдено по URL за отведённое время");
  return null;
}

/** Проходит форму Google: email → пароль → (опционально) 2FA → согласие. */
async function performGoogleAuth(page: Page, account: GoogleAccount, logger: Logger): Promise<void> {
  // Если Google показал выбор аккаунта — жмём «Использовать другой аккаунт».
  await clickByText(
    page,
    ["Use another account", "Add account", "Другой аккаунт", "Добавить аккаунт", "Использовать другой"],
    3000,
  ).catch(() => undefined);

  logger.info("elevenlabs.login", "Ввожу email Google", { email: account.email });
  const emailTyped = await typeInto(page, GOOGLE_SELECTORS.emailInput, account.email);
  if (!emailTyped) {
    throw new Error(`Не нашёл поле email Google (страница: ${safeUrl(page) || "неизвестно"})`);
  }
  await sleep(500);
  await clickByText(page, GOOGLE_SELECTORS.emailNextText, 8000);

  logger.info("elevenlabs.login", "Ввожу пароль Google");
  const passField = await waitForAny(page, GOOGLE_SELECTORS.passwordInput, 20_000);
  if (!passField) throw new Error("Не появилось поле пароля Google (возможно, требуется подтверждение устройства)");
  await sleep(500);
  await typeInto(page, GOOGLE_SELECTORS.passwordInput, account.password);
  await sleep(500);
  await clickByText(page, GOOGLE_SELECTORS.passwordNextText, 8000);
  await sleep(2500);

  // 2FA по TOTP, если настроен секрет и появилось поле.
  const totpField = await waitForAny(page, GOOGLE_SELECTORS.totpInput, 6000);
  if (totpField) {
    if (!account.totpSecret) {
      throw new Error("Google запросил 2FA-код, но totpSecret не указан в настройках");
    }
    const code = generateTotp(account.totpSecret);
    logger.info("elevenlabs.login", "Ввожу 2FA (TOTP) код");
    await typeInto(page, GOOGLE_SELECTORS.totpInput, code);
    await clickByText(page, GOOGLE_SELECTORS.passwordNextText, 8000);
    await sleep(2500);
  }

  // Экран подтверждения доступа (Continue/Allow), если появился.
  await clickByText(page, GOOGLE_SELECTORS.approveButtonText, 6000).catch(() => undefined);
}

/** Проверяет наличие маркеров залогиненного состояния. */
async function isLoggedIn(page: Page): Promise<boolean> {
  const el = await waitForAny(page, ELEVENLABS_SELECTORS.loggedInMarkers, 4000);
  return !!el;
}

async function waitForLogin(page: Page, timeout: number): Promise<boolean> {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    if (page.url().includes("/app/") && (await isLoggedIn(page))) return true;
    await sleep(1000);
  }
  // Иногда достаточно текста навигации
  return waitForText(page, ["Text to Speech", "Voice", "Home", "Studio"], 5000);
}
