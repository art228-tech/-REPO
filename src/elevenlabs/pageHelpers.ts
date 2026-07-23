import type { ElementHandle, Page } from "puppeteer-core";
import { sleep } from "../util/sleep.js";

/**
 * Ждёт появления любого из селекторов (видимого), возвращает первый handle.
 * Использует page.waitForSelector({visible:true}) для каждого селектора и
 * Promise.any — устойчиво к медленной загрузке и невалидным селекторам.
 */
export async function waitForAny(
  page: Page,
  selectors: string[],
  timeout = 20_000,
): Promise<ElementHandle<Element> | null> {
  try {
    return await Promise.any(
      selectors.map((selector) =>
        page
          .waitForSelector(selector, { visible: true, timeout })
          .then((el) => {
            if (!el) throw new Error("null");
            return el as ElementHandle<Element>;
          }),
      ),
    );
  } catch {
    return null;
  }
}

/** Печатает значение в первый доступный из selectors (с очисткой поля). */
export async function typeInto(
  page: Page,
  selectors: string[],
  value: string,
  options: { clear?: boolean; delay?: number; timeout?: number } = {},
): Promise<boolean> {
  const el = await waitForAny(page, selectors, options.timeout ?? 15_000);
  if (!el) return false;
  await el.click({ clickCount: 3 }).catch(() => undefined);
  if (options.clear !== false) {
    await page.keyboard.press("Backspace").catch(() => undefined);
  }
  await el.type(value, { delay: options.delay ?? 25 });
  return true;
}

/**
 * Ищет кликабельный элемент, текст которого содержит одну из подстрок,
 * и кликает по нему. Возвращает true при успехе.
 */
export async function clickByText(page: Page, texts: string[], timeout = 15_000): Promise<boolean> {
  const start = Date.now();
  const needles = texts.map((t) => t.toLowerCase());
  // ВАЖНО: код передаётся строкой (а не функцией), иначе в собранном бинарнике
  // (esbuild + pkg) Puppeteer падает с "Passed function cannot be serialized!".
  const code = `(() => {
    const needles = ${JSON.stringify(needles)};
    const candidates = Array.from(document.querySelectorAll('button, a, [role="button"], [role="menuitem"], [role="tab"], div[tabindex], span[tabindex]'));
    for (const el of candidates) {
      const label = (el.innerText || el.textContent || el.getAttribute('aria-label') || '').trim().toLowerCase();
      if (!label) continue;
      if (needles.some((n) => label.includes(n))) {
        const rect = el.getBoundingClientRect();
        if (rect.width > 0 && rect.height > 0) { el.click(); return true; }
      }
    }
    return false;
  })()`;
  while (Date.now() - start < timeout) {
    const clicked = (await page.evaluate(code)) as boolean;
    if (clicked) return true;
    await sleep(400);
  }
  return false;
}

/** Клик по элементу, найденному по одному из CSS-селекторов. */
export async function clickSelector(page: Page, selectors: string[], timeout = 15_000): Promise<boolean> {
  const el = await waitForAny(page, selectors, timeout);
  if (!el) return false;
  await el.click().catch(() => undefined);
  return true;
}

/** Проверяет, присутствует ли на странице любой из текстов (без учёта регистра). */
export async function textPresent(page: Page, texts: string[]): Promise<boolean> {
  const needles = texts.map((t) => t.toLowerCase());
  const code = `(() => {
    const needles = ${JSON.stringify(needles)};
    const body = (document.body && document.body.innerText ? document.body.innerText : '').toLowerCase();
    return needles.some((n) => body.includes(n));
  })()`;
  return (await page.evaluate(code)) as boolean;
}

/** Ждёт, пока на странице появится один из текстов. */
export async function waitForText(page: Page, texts: string[], timeout = 20_000): Promise<boolean> {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    if (await textPresent(page, texts)) return true;
    await sleep(400);
  }
  return false;
}

/** Извлекает первое целое число из текста (для чтения остатка кредитов). */
export function parseCreditsNumber(text: string): number | null {
  const match = text.replace(/[,\s]/g, "").match(/(\d{2,})/);
  if (!match) return null;
  const value = Number(match[1]);
  return Number.isFinite(value) ? value : null;
}
