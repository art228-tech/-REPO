import { afterEach, describe, expect, it } from "vitest";
import fs from "node:fs";
import fsp from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { Orchestrator } from "../src/core/orchestrator.js";
import { SimulatedDolphinService } from "../src/dolphin/simulated.js";
import { SimulatedElevenLabs } from "../src/elevenlabs/simulated.js";
import { Logger } from "../src/logging/logger.js";
import { checkDuration } from "../src/util/audioDuration.js";
import { baseConfig, ls, tmpDir, writeFile } from "./helpers.js";

function makeLogger(): Logger {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ellog-"));
  return new Logger({ logDir: dir, console: false });
}

const dirs: string[] = [];
async function make(): Promise<string> {
  const d = await tmpDir();
  dirs.push(d);
  return d;
}
afterEach(async () => {
  for (const d of dirs.splice(0)) await fsp.rm(d, { recursive: true, force: true });
});

describe("checkDuration", () => {
  it("возвращает too_short / ok / too_long по порогам", () => {
    expect(checkDuration(5, 10, 17)).toBe("too_short");
    expect(checkDuration(13, 10, 17)).toBe("ok");
    expect(checkDuration(20, 10, 17)).toBe("too_long");
  });
  it("null (неизвестно) считается допустимым", () => {
    expect(checkDuration(null, 10, 17)).toBe("unknown");
  });
  it("нулевые пороги отключают соответствующую границу", () => {
    expect(checkDuration(3, 0, 17)).toBe("ok");
    expect(checkDuration(999, 10, 0)).toBe("ok");
    expect(checkDuration(999, 0, 0)).toBe("ok");
  });
});

describe("Orchestrator: гейтинг по длительности (10–17 c, cps=15)", () => {
  async function setup() {
    const promptsDir = await make();
    const textsDir = await make();
    const downloadDir = await make();
    await writeFile(promptsDir, "v1.txt", "Мужской глубокий голос диктора, спокойный уверенный тон речи.");
    await writeFile(promptsDir, "v2.txt", "Женский мягкий тёплый голос, доброжелательный неспешный тон.");
    // cps=15 → секунды = длина/15
    await writeFile(textsDir, "1-short.txt", "к".repeat(60)); // 4.0 c — слишком коротко
    await writeFile(textsDir, "2-ok.txt", "к".repeat(200)); // 13.3 c — ок
    await writeFile(textsDir, "3-long.txt", "к".repeat(300)); // 20.0 c — слишком длинно
    await writeFile(textsDir, "4-ok.txt", "к".repeat(210)); // 14.0 c — ок
    return { promptsDir, textsDir, downloadDir };
  }

  it("отбраковывает слишком короткие/длинные и берёт следующий текст", async () => {
    const { promptsDir, textsDir, downloadDir } = await setup();
    const logger = makeLogger();
    const el = new SimulatedElevenLabs(logger, { initialCredits: 100000, latencyMs: 0, charsPerSecond: 15 });
    const orch = new Orchestrator(logger);
    const cfg = baseConfig({ promptsDir, textsDir, downloadDir, minDurationSec: 10, maxDurationSec: 17 });
    const status = await orch.run(cfg, { dolphin: new SimulatedDolphinService(logger), elevenlabs: el });

    expect(status.state).toBe("done");
    expect(status.filesDone).toBe(2); // 2-ok и 4-ok
    expect(status.filesRejected).toBe(2); // 1-short и 3-long

    // В папке скачивания только принятые файлы
    const downloaded = await ls(downloadDir);
    expect(downloaded.length).toBe(2);
    expect(downloaded.some((f) => f.includes("2-ok"))).toBe(true);
    expect(downloaded.some((f) => f.includes("4-ok"))).toBe(true);

    // Отбракованные тексты остаются на диске (не удалены), принятые удалены
    const remainingTexts = await ls(textsDir);
    expect(remainingTexts.sort()).toEqual(["1-short.txt", "3-long.txt"]);
  });

  it("голос переключается только на успешной озвучке (отбракованный текст не сдвигает голос)", async () => {
    const { promptsDir, textsDir, downloadDir } = await setup();
    const logger = makeLogger();
    const el = new SimulatedElevenLabs(logger, { initialCredits: 100000, latencyMs: 0, charsPerSecond: 15 });
    const orch = new Orchestrator(logger);
    const cfg = baseConfig({ promptsDir, textsDir, downloadDir, minDurationSec: 10, maxDurationSec: 17 });
    await orch.run(cfg, { dolphin: new SimulatedDolphinService(logger), elevenlabs: el });

    const accepted = (await ls(downloadDir)).sort();
    // 2-ok должен быть озвучен первым голосом, 4-ok — вторым
    expect(accepted.find((f) => f.includes("2-ok"))).toContain("AutoVoice-1");
    expect(accepted.find((f) => f.includes("4-ok"))).toContain("AutoVoice-2");
  });

  it("при выключенном гейтинге (0/0) короткие тексты не отбраковываются", async () => {
    const { promptsDir, textsDir, downloadDir } = await setup();
    const logger = makeLogger();
    const el = new SimulatedElevenLabs(logger, { initialCredits: 100000, latencyMs: 0, charsPerSecond: 15 });
    const orch = new Orchestrator(logger);
    const cfg = baseConfig({ promptsDir, textsDir, downloadDir, minDurationSec: 0, maxDurationSec: 0 });
    const status = await orch.run(cfg, { dolphin: new SimulatedDolphinService(logger), elevenlabs: el });
    expect(status.filesRejected).toBe(0);
    expect(status.filesDone).toBe(4);
  });
});
