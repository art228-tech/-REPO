import { afterEach, describe, expect, it } from "vitest";
import fs from "node:fs";
import fsp from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { Orchestrator } from "../src/core/orchestrator.js";
import { SimulatedDolphinService } from "../src/dolphin/simulated.js";
import { SimulatedElevenLabs } from "../src/elevenlabs/simulated.js";
import { Logger } from "../src/logging/logger.js";
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

async function setupDirs(numTexts: number, textLen = 40) {
  const promptsDir = await make();
  const textsDir = await make();
  const downloadDir = await make();
  await writeFile(promptsDir, "voice1.txt", "Мужской глубокий голос диктора, спокойный уверенный тон.");
  await writeFile(promptsDir, "voice2.txt", "Женский мягкий голос, тёплый доброжелательный тон речи.");
  for (let i = 0; i < numTexts; i++) {
    await writeFile(textsDir, `text${i + 1}.txt`, "Т".repeat(textLen) + ` #${i + 1}`);
  }
  return { promptsDir, textsDir, downloadDir };
}

describe("Orchestrator (dry-run с симуляторами)", () => {
  it("проходит полный happy-path: 3 голоса, все тексты озвучены и удалены, профиль удалён", async () => {
    const { promptsDir, textsDir, downloadDir } = await setupDirs(4);
    const logger = makeLogger();
    const dolphin = new SimulatedDolphinService(logger);
    const el = new SimulatedElevenLabs(logger, { initialCredits: 100000, latencyMs: 0 });
    const orch = new Orchestrator(logger);

    const cfg = baseConfig({ promptsDir, textsDir, downloadDir });
    const status = await orch.run(cfg, { dolphin, elevenlabs: el });

    expect(status.state).toBe("done");
    expect(status.voicesCreated).toBe(3);
    expect(el.designedVoices.map((v) => v.name)).toEqual(["AutoVoice-1", "AutoVoice-2", "AutoVoice-3"]);
    expect(status.filesDone).toBe(4);
    // Все текстовые файлы удалены
    expect(await ls(textsDir)).toEqual([]);
    // Скачано 4 файла
    expect((await ls(downloadDir)).length).toBe(4);
    // Профиль создан, запущен, остановлен и удалён
    expect(dolphin.created.length).toBe(1);
    expect(dolphin.started).toEqual(dolphin.created);
    expect(dolphin.stopped).toEqual(dolphin.created);
    expect(dolphin.deleted).toEqual(dolphin.created);
  });

  it("голоса используются по кругу", async () => {
    const { promptsDir, textsDir, downloadDir } = await setupDirs(5);
    const logger = makeLogger();
    const el = new SimulatedElevenLabs(logger, { initialCredits: 100000, latencyMs: 0 });
    const orch = new Orchestrator(logger);
    const cfg = baseConfig({ promptsDir, textsDir, downloadDir });
    await orch.run(cfg, { dolphin: new SimulatedDolphinService(logger), elevenlabs: el });

    const voicesUsed = el.synthesized.map((p) => path.basename(p).match(/__(AutoVoice-\d)/)?.[1]);
    expect(voicesUsed).toEqual(["AutoVoice-1", "AutoVoice-2", "AutoVoice-3", "AutoVoice-1", "AutoVoice-2"]);
  });

  it("останавливается при исчерпании кредитов, оставляя необработанные тексты", async () => {
    const { promptsDir, textsDir, downloadDir } = await setupDirs(6, 40);
    const logger = makeLogger();
    // Бюджета хватает ровно на 2 озвучки (~43 символа каждая).
    const el = new SimulatedElevenLabs(logger, { initialCredits: 110, latencyMs: 0 });
    const orch = new Orchestrator(logger);
    const cfg = baseConfig({ promptsDir, textsDir, downloadDir });
    const status = await orch.run(cfg, { dolphin: new SimulatedDolphinService(logger), elevenlabs: el });

    expect(status.state).toBe("done");
    expect(status.filesDone).toBe(2);
    // Часть текстов осталась на диске (не удалена)
    expect((await ls(textsDir)).length).toBeGreaterThan(0);
    expect((await ls(downloadDir)).length).toBe(2);
  });

  it("пропускает слишком короткий промпт и всё равно создаёт нужное число голосов", async () => {
    const promptsDir = await make();
    const textsDir = await make();
    const downloadDir = await make();
    await writeFile(promptsDir, "bad.txt", "коротко");
    await writeFile(promptsDir, "good1.txt", "Мужской глубокий голос диктора, спокойный уверенный тон речи.");
    await writeFile(promptsDir, "good2.txt", "Женский мягкий тёплый голос, доброжелательный неспешный тон.");
    await writeFile(textsDir, "t1.txt", "Первый текст для озвучки, достаточно длинный для теста.");

    const logger = makeLogger();
    const el = new SimulatedElevenLabs(logger, { initialCredits: 100000, latencyMs: 0 });
    const orch = new Orchestrator(logger);
    const cfg = baseConfig({ promptsDir, textsDir, downloadDir, voiceDesign: { ...baseConfig().voiceDesign, voicesToCreate: 2 } });
    const status = await orch.run(cfg, { dolphin: new SimulatedDolphinService(logger), elevenlabs: el });

    expect(status.state).toBe("done");
    expect(status.voicesCreated).toBe(2);
    expect(status.filesDone).toBe(1);
  });

  it("НЕ удаляет профиль при ошибке (оставляет для диагностики)", async () => {
    const { promptsDir, textsDir, downloadDir } = await setupDirs(1);
    const logger = makeLogger();
    const dolphin = new SimulatedDolphinService(logger);
    // Симулятор ElevenLabs, падающий на входе через Google.
    const failingEl = {
      async connect() {},
      async loginWithGoogle() {
        throw new Error("login boom");
      },
      async getRemainingCredits() {
        return Number.POSITIVE_INFINITY;
      },
      async designVoice() {
        throw new Error("nope");
      },
      async synthesize() {
        throw new Error("nope");
      },
      async close() {},
    };
    const orch = new Orchestrator(logger);
    const cfg = baseConfig({ promptsDir, textsDir, downloadDir, deleteProfileOnFinish: true });
    const status = await orch.run(cfg, { dolphin, elevenlabs: failingEl as any });

    expect(status.state).toBe("error");
    expect(dolphin.created.length).toBe(1);
    expect(dolphin.stopped.length).toBe(1);
    expect(dolphin.deleted.length).toBe(0); // профиль оставлен
  });

  it("не удаляет профиль, если deleteProfileOnFinish=false", async () => {
    const { promptsDir, textsDir, downloadDir } = await setupDirs(1);
    const logger = makeLogger();
    const dolphin = new SimulatedDolphinService(logger);
    const el = new SimulatedElevenLabs(logger, { initialCredits: 100000, latencyMs: 0 });
    const orch = new Orchestrator(logger);
    const cfg = baseConfig({ promptsDir, textsDir, downloadDir, deleteProfileOnFinish: false });
    await orch.run(cfg, { dolphin, elevenlabs: el });
    expect(dolphin.stopped.length).toBe(1);
    expect(dolphin.deleted.length).toBe(0);
  });
});
