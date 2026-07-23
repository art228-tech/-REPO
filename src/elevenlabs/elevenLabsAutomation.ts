import puppeteer, { Browser, Page } from "puppeteer-core";
import { GoogleAccount } from "../config/schema.js";
import { AutomationEndpoint } from "../dolphin/types.js";
import { Logger } from "../logging/logger.js";
import { sleep } from "../util/sleep.js";
import { ELEVENLABS } from "./constants.js";
import { loginWithGoogle } from "./googleLogin.js";
import { parseCreditsNumber } from "./pageHelpers.js";
import { synthesize } from "./tts.js";
import {
  CreatedVoice,
  DesignVoiceParams,
  IElevenLabsAutomation,
  SynthesizeParams,
  SynthesizeResult,
} from "./types.js";
import { designVoice } from "./voiceDesign.js";

/**
 * Реальная автоматизация ElevenLabs поверх антидетект-браузера Dolphin Anty.
 * Подключается к запущенному профилю по CDP (Puppeteer) и управляет вкладкой.
 */
export class ElevenLabsAutomation implements IElevenLabsAutomation {
  private browser: Browser | null = null;
  private page: Page | null = null;

  constructor(private readonly logger: Logger) {}

  async connect(endpoint: AutomationEndpoint): Promise<void> {
    const browserWSEndpoint = `ws://127.0.0.1:${endpoint.port}${endpoint.wsEndpoint}`;
    this.logger.info("elevenlabs", "Подключаюсь к профилю Dolphin по CDP", { port: endpoint.port });
    this.browser = await puppeteer.connect({
      browserWSEndpoint,
      defaultViewport: null,
    });
    const pages = await this.browser.pages();
    this.page = pages.find((p) => !p.url().startsWith("devtools://")) ?? (await this.browser.newPage());
    await this.page.bringToFront().catch(() => undefined);
    this.logger.success("elevenlabs", "Подключение к браузеру установлено");
  }

  private requirePage(): Page {
    if (!this.page) throw new Error("Браузер не подключён (page == null)");
    return this.page;
  }

  private requireBrowser(): Browser {
    if (!this.browser) throw new Error("Браузер не подключён (browser == null)");
    return this.browser;
  }

  async loginWithGoogle(account: GoogleAccount): Promise<void> {
    // Вход может завершиться на другой вкладке — используем ту, что вернул логин.
    this.page = await loginWithGoogle(this.requireBrowser(), this.requirePage(), account, this.logger);
  }

  async getRemainingCredits(): Promise<number> {
    const page = this.requirePage();
    try {
      await page.goto(ELEVENLABS.USAGE_URL, { waitUntil: "domcontentloaded", timeout: 45_000 });
      await sleep(2000);
      // Строкой (не функцией) — ради совместимости с собранным бинарником.
      const bodyText = ((await page.evaluate(
        "document.body && document.body.innerText ? document.body.innerText : ''",
      )) as string) ?? "";
      // Ищем строки вида "12,345 / 100,000" или "credits remaining".
      const remainingMatch =
        bodyText.match(/([\d.,\s]+)\s*(?:credits|characters)?\s*(?:remaining|left|осталось)/i) ||
        bodyText.match(/(?:remaining|осталось)\s*[:\-]?\s*([\d.,\s]+)/i);
      if (remainingMatch) {
        const value = parseCreditsNumber(remainingMatch[1]);
        if (value !== null) {
          this.logger.info("elevenlabs", `Остаток кредитов: ${value}`);
          return value;
        }
      }
      // Формат "used / total": remaining = total - used.
      const ratio = bodyText.match(/([\d.,]+)\s*\/\s*([\d.,]+)/);
      if (ratio) {
        const used = parseCreditsNumber(ratio[1]) ?? 0;
        const total = parseCreditsNumber(ratio[2]) ?? 0;
        const remaining = Math.max(0, total - used);
        this.logger.info("elevenlabs", `Остаток кредитов (total-used): ${remaining}`);
        return remaining;
      }
    } catch (error) {
      this.logger.warn("elevenlabs", "Не удалось прочитать остаток кредитов", { error: String(error) });
    }
    // Неизвестно — не блокируем работу, полагаемся на OutOfCreditsError.
    return Number.POSITIVE_INFINITY;
  }

  async designVoice(params: DesignVoiceParams): Promise<CreatedVoice> {
    return designVoice(this.requirePage(), params, this.logger);
  }

  async synthesize(params: SynthesizeParams): Promise<SynthesizeResult> {
    return synthesize(this.requirePage(), params, this.logger);
  }

  async close(): Promise<void> {
    if (this.browser) {
      // disconnect, не close: профиль остановит Dolphin через stopProfile.
      await this.browser.disconnect().catch(() => undefined);
      this.browser = null;
      this.page = null;
      this.logger.info("elevenlabs", "Отключился от браузера");
    }
  }
}
