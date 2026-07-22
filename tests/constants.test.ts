import { describe, expect, it } from "vitest";
import {
  chunkText,
  ELEVENLABS,
  truncateAtWord,
  validatePreviewText,
  validateVoiceDescription,
} from "../src/elevenlabs/constants.js";

describe("validateVoiceDescription", () => {
  it("отбраковывает слишком короткое описание", () => {
    const r = validateVoiceDescription("too short");
    expect(r.ok).toBe(false);
    expect(r.reason).toContain("коротк");
  });

  it("принимает нормальное описание", () => {
    const desc = "Мужской глубокий голос диктора, спокойный и уверенный тон, среднего темпа.";
    const r = validateVoiceDescription(desc);
    expect(r.ok).toBe(true);
    expect(r.truncated).toBe(false);
  });

  it("обрезает слишком длинное описание по границе слова", () => {
    const long = "слово ".repeat(400).trim();
    const r = validateVoiceDescription(long);
    expect(r.ok).toBe(true);
    expect(r.truncated).toBe(true);
    expect(r.value.length).toBeLessThanOrEqual(ELEVENLABS.VOICE_DESCRIPTION_MAX);
  });

  it("нормализует пробелы", () => {
    const r = validateVoiceDescription("Мужской    голос    диктора    среднего    темпа    речи здесь");
    expect(r.value).not.toContain("  ");
  });
});

describe("validatePreviewText", () => {
  it("пустой preview → авто-генерация (ok:false)", () => {
    expect(validatePreviewText("").ok).toBe(false);
  });

  it("короткий preview → авто-генерация", () => {
    expect(validatePreviewText("короткий текст").ok).toBe(false);
  });

  it("нормальный preview принимается", () => {
    const text = "a".repeat(200);
    const r = validatePreviewText(text);
    expect(r.ok).toBe(true);
  });

  it("длинный preview обрезается", () => {
    const text = "слово ".repeat(400);
    const r = validatePreviewText(text);
    expect(r.ok).toBe(true);
    expect(r.truncated).toBe(true);
    expect(r.value.length).toBeLessThanOrEqual(ELEVENLABS.PREVIEW_TEXT_MAX);
  });
});

describe("truncateAtWord", () => {
  it("не трогает короткие строки", () => {
    expect(truncateAtWord("hello", 100)).toBe("hello");
  });
  it("режет по границе слова", () => {
    const r = truncateAtWord("one two three four five", 12);
    expect(r.length).toBeLessThanOrEqual(12);
    expect(r.endsWith(" ")).toBe(false);
  });
});

describe("chunkText", () => {
  it("короткий текст → один кусок", () => {
    expect(chunkText("hello world", 5000)).toEqual(["hello world"]);
  });
  it("пустой текст → пустой массив", () => {
    expect(chunkText("   ", 5000)).toEqual([]);
  });
  it("длинный текст режется на несколько частей в пределах лимита", () => {
    const sentence = "Это предложение номер X. ";
    const text = sentence.repeat(500);
    const chunks = chunkText(text, 200);
    expect(chunks.length).toBeGreaterThan(1);
    for (const c of chunks) expect(c.length).toBeLessThanOrEqual(200);
    expect(chunks.join(" ").replace(/\s+/g, "")).toContain("предложение");
  });
  it("одно очень длинное предложение без разделителей режется жёстко", () => {
    const text = "a".repeat(1000);
    const chunks = chunkText(text, 100);
    expect(chunks.length).toBe(10);
  });
});
