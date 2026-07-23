import type { Frame, Page } from "puppeteer-core";
import { Logger } from "../logging/logger.js";
import { sleep } from "../util/sleep.js";

/**
 * КРИТИЧЕСКИ ВАЖНО: в собранном бинарнике (esbuild + pkg) Puppeteer НЕ умеет
 * сериализовать функции. Поэтому ломается не только page.evaluate(fn), но и
 * page.$/$$/waitForSelector и любые операции с ElementHandle (они внутри
 * передают функцию в страницу). Работает только СТРОКОВЫЙ evaluate и CDP-ввод
 * (keyboard/mouse). Поэтому здесь ВСЁ сделано через frame.evaluate("...") и
 * page.keyboard — без ElementHandle. Так действия срабатывают и в .exe.
 */

/** Список фреймов страницы (main + вложенные), безопасно. */
function framesOf(page: Page): Frame[] {
  try {
    return page.frames();
  } catch {
    return [];
  }
}

export interface FoundSelector {
  frame: Frame;
  selector: string;
}

/** Проверяет в конкретном фрейме, есть ли видимый элемент по одному из селекторов. Возвращает найденный селектор. */
async function matchInFrame(frame: Frame, selectors: string[]): Promise<string | null> {
  const code = `(() => {
    const sels = ${JSON.stringify(selectors)};
    for (const s of sels) {
      let el = null;
      try { el = document.querySelector(s); } catch (e) { continue; }
      if (el) {
        const vis = !!(el.offsetWidth || el.offsetHeight || (el.getClientRects && el.getClientRects().length));
        if (vis) return s;
      }
    }
    return null;
  })()`;
  try {
    const res = (await frame.evaluate(code)) as string | null;
    return typeof res === "string" ? res : null;
  } catch {
    return null;
  }
}

/** Ищет по всем фреймам первый видимый элемент по любому селектору (опрос до таймаута). */
export async function findAny(page: Page, selectors: string[], timeout = 20_000): Promise<FoundSelector | null> {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    for (const frame of framesOf(page)) {
      const selector = await matchInFrame(frame, selectors);
      if (selector) return { frame, selector };
    }
    await sleep(300);
  }
  return null;
}

/** Возвращает true, если элемент по одному из селекторов виден (для проверок «появилось ли»). */
export async function waitForAny(page: Page, selectors: string[], timeout = 20_000): Promise<boolean> {
  return (await findAny(page, selectors, timeout)) !== null;
}

/** Читает значение поля (input/textarea/contenteditable) по селектору в конкретном фрейме. */
async function readFieldValue(frame: Frame, selector: string): Promise<string | null> {
  const code = `(() => {
    const el = document.querySelector(${JSON.stringify(selector)});
    if (!el) return null;
    if (el.isContentEditable) return String(el.textContent || '');
    return String(el.value != null ? el.value : '');
  })()`;
  try {
    const v = await frame.evaluate(code);
    return typeof v === "string" ? v : null;
  } catch {
    return null;
  }
}

function valueOk(v: string | null, value: string): boolean {
  if (v === null) return false;
  const a = v.trim();
  const b = value.trim();
  return a.length > 0 && (a === b || a.includes(b));
}

/**
 * Универсальный ввод значения в поле по любому из селекторов (по всем фреймам).
 * Пробует несколько способов и ПРОВЕРЯЕТ, что значение реально попало в поле:
 *  1) JS: нативный сеттер value + события input/change (совместимо с React) /
 *     textContent для contenteditable;
 *  2) фокус + CDP-клавиатура (page.keyboard.type);
 *  3) повтор JS-сеттера.
 * Всё — через строковый evaluate и keyboard (безопасно для бинарника).
 */
export async function typeInto(
  page: Page,
  selectors: string[],
  value: string,
  options: { delay?: number; timeout?: number } = {},
): Promise<boolean> {
  const found = await findAny(page, selectors, options.timeout ?? 15_000);
  if (!found) return false;
  const { frame, selector } = found;
  const sel = JSON.stringify(selector);
  const val = JSON.stringify(value);

  const setViaJs = `(() => {
    const el = document.querySelector(${sel});
    if (!el) return false;
    try { el.focus(); } catch (e) {}
    if (el.isContentEditable) {
      el.textContent = ${val};
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    }
    const proto = el.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
    let desc = null;
    try { desc = Object.getOwnPropertyDescriptor(proto, 'value'); } catch (e) {}
    try { el.value = ''; } catch (e) {}
    if (desc && desc.set) { desc.set.call(el, ${val}); } else { el.value = ${val}; }
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
    return true;
  })()`;

  // Способ 1: JS-сеттер
  try {
    await frame.evaluate(setViaJs);
  } catch {
    /* ignore */
  }
  if (valueOk(await readFieldValue(frame, selector), value)) return true;

  // Способ 2: фокус + клавиатура
  try {
    await frame.evaluate(`(() => { const el = document.querySelector(${sel}); if (el) { el.focus(); if(!el.isContentEditable){ try{el.value='';}catch(e){} } } })()`);
    await page.keyboard.type(value, { delay: options.delay ?? 15 });
  } catch {
    /* ignore */
  }
  if (valueOk(await readFieldValue(frame, selector), value)) return true;

  // Способ 3: повтор JS-сеттера
  try {
    await frame.evaluate(setViaJs);
  } catch {
    /* ignore */
  }
  return valueOk(await readFieldValue(frame, selector), value);
}

const CLICKABLE =
  'button, a, [role="button"], [role="menuitem"], [role="tab"], [role="option"], [role="radio"], div[tabindex], span[tabindex], input[type="submit"], input[type="button"], label';

/** Кликает по элементу, чей текст/aria-label содержит одну из строк (по всем фреймам, строковый evaluate). */
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
        const vis = !!(el.offsetWidth || el.offsetHeight || (el.getClientRects && el.getClientRects().length));
        if (vis) { el.scrollIntoView({ block: 'center' }); el.click(); return true; }
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

/** Клик по элементу, найденному по одному из CSS-селекторов (строковый evaluate, по всем фреймам). */
export async function clickSelector(page: Page, selectors: string[], timeout = 15_000): Promise<boolean> {
  const found = await findAny(page, selectors, timeout);
  if (!found) return false;
  const code = `(() => {
    const el = document.querySelector(${JSON.stringify(found.selector)});
    if (el) { el.scrollIntoView({ block: 'center' }); el.click(); return true; }
    return false;
  })()`;
  try {
    return (await found.frame.evaluate(code)) as boolean;
  } catch {
    return false;
  }
}

/** Считает суммарное число элементов по селекторам (по всем фреймам). */
export async function countAny(page: Page, selectors: string[]): Promise<number> {
  const code = `(() => {
    const sels = ${JSON.stringify(selectors)};
    let n = 0;
    for (const s of sels) { try { n += document.querySelectorAll(s).length; } catch (e) {} }
    return n;
  })()`;
  let total = 0;
  for (const frame of framesOf(page)) {
    try {
      total += Number(await frame.evaluate(code)) || 0;
    } catch {
      /* ignore */
    }
  }
  return total;
}

/** Кликает по N-му (index) совпавшему элементу среди селекторов (по всем фреймам). */
export async function clickNth(page: Page, selectors: string[], index: number): Promise<boolean> {
  const code = `(() => {
    const sels = ${JSON.stringify(selectors)};
    let list = [];
    for (const s of sels) { try { list = list.concat(Array.from(document.querySelectorAll(s))); } catch (e) {} }
    const el = list[${index}] || list[0];
    if (el) { el.scrollIntoView({ block: 'center' }); el.click(); return true; }
    return false;
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
 * список полей ввода и кнопок. Помогает точно понять, что на странице.
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
