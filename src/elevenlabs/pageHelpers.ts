import type { ElementHandle, Frame, Page } from "puppeteer-core";
import { Logger } from "../logging/logger.js";
import { sleep } from "../util/sleep.js";

/**
 * ВАЖНО: во всех функциях используется только строковая форма evaluate и
 * нативные методы handle (getProperty/boundingBox/click/focus/type). Передача
 * функций в evaluate ломается в собранном бинарнике (esbuild+pkg:
 * "Passed function cannot be serialized!"), поэтому её здесь нет.
 *
 * Все действия — фрейм-осведомлённые (ищем по всем фреймам страницы) и с
 * несколькими стратегиями, чтобы срабатывать наверняка.
 */

/** Список фреймов страницы (main + вложенные), безопасно. */
function framesOf(page: Page): Frame[] {
  try {
    return page.frames();
  } catch {
    return [];
  }
}

export interface FoundElement {
  frame: Frame;
  el: ElementHandle<Element>;
}

/**
 * Проверяет видимость элемента по offsetWidth/offsetHeight (нативно, через
 * getProperty). ВАЖНО: boundingBox() у Puppeteer в popup-окнах антидетект-
 * браузера часто возвращает null (окно «не отрисовано» для CDP), хотя элемент
 * реально виден, поэтому используем layout-свойства, как в диагностике.
 */
async function isVisibleHandle(el: ElementHandle<Element>): Promise<boolean> {
  try {
    const w = Number(await (await el.getProperty("offsetWidth")).jsonValue()) || 0;
    const h = Number(await (await el.getProperty("offsetHeight")).jsonValue()) || 0;
    if (w > 0 || h > 0) return true;
    const rects = Number(await (await el.getProperty("clientHeight")).jsonValue()) || 0;
    return rects > 0;
  } catch {
    return false;
  }
}

/** Ищет по всем фреймам первый видимый элемент по любому из селекторов. */
export async function findAny(page: Page, selectors: string[], timeout = 20_000): Promise<FoundElement | null> {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    for (const frame of framesOf(page)) {
      for (const selector of selectors) {
        try {
          const els = (await frame.$$(selector)) as ElementHandle<Element>[];
          for (const el of els) {
            if (await isVisibleHandle(el)) return { frame, el };
          }
        } catch {
          // навигация/пересоздание контекста/невалидный селектор — пробуем снова
        }
      }
    }
    await sleep(300);
  }
  return null;
}

/** Обратная совместимость: возвращает только handle. */
export async function waitForAny(page: Page, selectors: string[], timeout = 20_000): Promise<ElementHandle<Element> | null> {
  const found = await findAny(page, selectors, timeout);
  return found?.el ?? null;
}

/** Читает свойство value элемента (нативно, без сериализации функций). */
async function readValue(el: ElementHandle<Element>): Promise<string | null> {
  try {
    const prop = await el.getProperty("value");
    const val = await prop.jsonValue();
    return typeof val === "string" ? val : null;
  } catch {
    return null;
  }
}

async function valueEntered(el: ElementHandle<Element>, value: string): Promise<boolean> {
  const v = await readValue(el);
  if (v === null) return true; // не поле ввода (нельзя проверить) — считаем успехом
  const trimmed = v.trim();
  return trimmed.length > 0 && (trimmed === value.trim() || trimmed.includes(value.trim()));
}

/**
 * Вводит значение в первое подходящее поле (по всем фреймам), пробуя несколько
 * методов и проверяя, что значение реально попало в поле:
 *  1) тройной клик + Backspace + type
 *  2) focus + keyboard.type
 *  3) JS: установка value активному элементу + события input/change
 */
export async function typeInto(
  page: Page,
  selectors: string[],
  value: string,
  options: { delay?: number; timeout?: number } = {},
): Promise<boolean> {
  const found = await findAny(page, selectors, options.timeout ?? 15_000);
  if (!found) return false;
  const { frame, el } = found;
  const delay = options.delay ?? 20;

  // Метод 1: focus + клавиатура. Самый надёжный, не требует «отрисовки» окна
  // (в отличие от el.click(), который использует box model и падает в popup).
  try {
    await el.focus();
    // Выделить всё и стереть (Ctrl/Cmd+A → Backspace), затем печатать.
    await page.keyboard.down("Control").catch(() => undefined);
    await page.keyboard.press("KeyA").catch(() => undefined);
    await page.keyboard.up("Control").catch(() => undefined);
    await page.keyboard.press("Backspace").catch(() => undefined);
    await page.keyboard.type(value, { delay });
  } catch {
    /* ignore */
  }
  if (await valueEntered(el, value)) return true;

  // Метод 2: JS-установка value активному элементу (строковый evaluate).
  try {
    await el.focus();
    const code = `(() => { const el = document.activeElement; if (el) { el.value = ${JSON.stringify(
      value,
    )}; el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); return true; } return false; })()`;
    await frame.evaluate(code);
  } catch {
    /* ignore */
  }
  if (await valueEntered(el, value)) return true;

  // Метод 3: тройной клик + печать (если окно всё же отрисовано).
  try {
    await el.click({ clickCount: 3 });
    await page.keyboard.press("Backspace").catch(() => undefined);
    await el.type(value, { delay });
  } catch {
    /* ignore */
  }
  return valueEntered(el, value);
}

const CLICKABLE =
  'button, a, [role="button"], [role="menuitem"], [role="tab"], [role="option"], div[tabindex], span[tabindex], input[type="submit"], input[type="button"]';

/** Кликает по элементу, чей текст/aria-label содержит одну из строк (по всем фреймам). */
export async function clickByText(page: Page, texts: string[], timeout = 15_000): Promise<boolean> {
  const start = Date.now();
  const needles = texts.map((t) => t.toLowerCase());
  const code = `(() => {
    const needles = ${JSON.stringify(needles)};
    const els = Array.from(document.querySelectorAll(${JSON.stringify(CLICKABLE)}));
    for (const el of els) {
      const label = (el.innerText || el.textContent || el.getAttribute('aria-label') || el.value || '').trim().toLowerCase();
      if (!label) continue;
      if (needles.some((n) => label.includes(n))) {
        const r = el.getBoundingClientRect();
        if (r.width > 0 && r.height > 0) { el.scrollIntoView({block:'center'}); el.click(); return true; }
      }
    }
    return false;
  })()`;
  while (Date.now() - start < timeout) {
    for (const frame of framesOf(page)) {
      try {
        if ((await frame.evaluate(code)) as boolean) return true;
      } catch {
        /* навигация — повторим */
      }
    }
    await sleep(400);
  }
  return false;
}

/** Клик по элементу, найденному по одному из CSS-селекторов (по всем фреймам). */
export async function clickSelector(page: Page, selectors: string[], timeout = 15_000): Promise<boolean> {
  const found = await findAny(page, selectors, timeout);
  if (!found) return false;
  try {
    await found.el.click();
    return true;
  } catch {
    return false;
  }
}

/** Проверяет наличие любого из текстов на странице (по всем фреймам). */
export async function textPresent(page: Page, texts: string[]): Promise<boolean> {
  const needles = texts.map((t) => t.toLowerCase());
  const code = `(() => {
    const needles = ${JSON.stringify(needles)};
    const body = (document.body && document.body.innerText ? document.body.innerText : '').toLowerCase();
    return needles.some((n) => body.includes(n));
  })()`;
  for (const frame of framesOf(page)) {
    try {
      if ((await frame.evaluate(code)) as boolean) return true;
    } catch {
      /* ignore */
    }
  }
  return false;
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

/**
 * Собирает и логирует диагностику страницы: по каждому фрейму — заголовок,
 * список полей ввода и кнопок. Помогает точно понять, что на странице, а не
 * угадывать селекторы.
 */
export async function dumpDiagnostics(page: Page, logger: Logger, label: string): Promise<void> {
  const code = `(() => {
    const inputs = Array.from(document.querySelectorAll('input, textarea, [contenteditable="true"]')).slice(0, 30).map((e) => ({
      tag: e.tagName, type: e.type || '', name: e.name || '', id: e.id || '',
      ph: e.placeholder || '', al: e.getAttribute('aria-label') || '',
      vis: !!(e.offsetWidth || e.offsetHeight)
    }));
    const buttons = Array.from(document.querySelectorAll('button, [role="button"], a')).slice(0, 30)
      .map((b) => (b.innerText || b.textContent || b.getAttribute('aria-label') || '').trim().slice(0, 40)).filter(Boolean);
    return { title: document.title, url: location.href, inputs, buttons };
  })()`;
  const frameInfos: unknown[] = [];
  for (const frame of framesOf(page)) {
    let url = "";
    try {
      url = frame.url();
    } catch {
      /* ignore */
    }
    try {
      const data = await frame.evaluate(code);
      frameInfos.push({ frameUrl: url, ...(data as object) });
    } catch (error) {
      frameInfos.push({ frameUrl: url, error: String(error) });
    }
  }
  logger.info("elevenlabs.diag", `Диагностика: ${label}`, { frames: frameInfos });
}
