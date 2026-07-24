import { describe, expect, it } from "vitest";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { Logger, maskSecrets } from "../src/logging/logger.js";

function makeLogger(): Logger {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ellog-"));
  return new Logger({ logDir: dir, console: false });
}

describe("maskSecrets", () => {
  it("маскирует пароли и токены", () => {
    const masked = maskSecrets({ password: "supersecret", email: "a@b.c", token: "abcdef" });
    expect(masked.password).not.toBe("supersecret");
    expect(masked.email).toBe("a@b.c");
    expect(String(masked.token)).toContain("***");
  });

  it("рекурсивно маскирует вложенные объекты", () => {
    const masked = maskSecrets({ google: { password: "hunter2xxxx", email: "x@y.z" } }) as any;
    expect(masked.google.password).not.toBe("hunter2xxxx");
    expect(masked.google.email).toBe("x@y.z");
  });
});

describe("Logger", () => {
  it("хранит записи в буфере и эмитит события", () => {
    const logger = makeLogger();
    const seen: string[] = [];
    logger.on("entry", (e) => seen.push(e.message));
    logger.info("test", "привет");
    logger.error("test", "ошибка");
    expect(seen).toEqual(["привет", "ошибка"]);
    expect(logger.recent().length).toBe(2);
  });

  it("dumpText содержит записи и маскирует секреты", () => {
    const logger = makeLogger();
    logger.info("test", "line", { password: "verysecretvalue" });
    const text = logger.dumpText();
    expect(text).toContain("line");
    expect(text).not.toContain("verysecretvalue");
  });

  it("уважает минимальный уровень", () => {
    const logger = makeLogger();
    logger.setMinLevel("warn");
    logger.info("t", "skip");
    logger.warn("t", "keep");
    const messages = logger.recent().map((e) => e.message);
    expect(messages).toContain("keep");
    expect(messages).not.toContain("skip");
  });
});
