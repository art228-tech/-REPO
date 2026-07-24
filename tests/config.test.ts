import { describe, expect, it } from "vitest";
import { validateConfig } from "../src/config/schema.js";
import { baseConfig } from "./helpers.js";

describe("validateConfig", () => {
  it("принимает корректный конфиг", () => {
    const r = validateConfig(baseConfig());
    expect(r.ok).toBe(true);
    expect(r.config?.voiceDesign.voicesToCreate).toBe(3);
  });

  it("сообщает об отсутствии обязательных папок", () => {
    const cfg = baseConfig();
    // @ts-expect-error намеренно ломаем
    delete cfg.downloadDir;
    const r = validateConfig(cfg);
    expect(r.ok).toBe(false);
    expect(r.errors?.some((e) => e.path === "downloadDir")).toBe(true);
  });

  it("валидирует диапазон порта прокси", () => {
    const cfg = baseConfig();
    cfg.proxy.port = 99999 as unknown as number;
    const r = validateConfig(cfg);
    expect(r.ok).toBe(false);
    expect(r.errors?.some((e) => e.path.startsWith("proxy.port"))).toBe(true);
  });

  it("коэрсит числовые строки", () => {
    const cfg = baseConfig();
    // @ts-expect-error строка вместо числа — должна скоэрситься
    cfg.voiceDesign.voicesToCreate = "2";
    const r = validateConfig(cfg);
    expect(r.ok).toBe(true);
    expect(r.config?.voiceDesign.voicesToCreate).toBe(2);
  });

  it("требует Google email и пароль", () => {
    const cfg = baseConfig();
    cfg.google.email = "";
    cfg.google.password = "";
    const r = validateConfig(cfg);
    expect(r.ok).toBe(false);
  });
});
