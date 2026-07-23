import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { AppConfig } from "../src/config/schema.js";

/** Создаёт временную директорию для теста. */
export async function tmpDir(prefix = "elauto-"): Promise<string> {
  return fs.mkdtemp(path.join(os.tmpdir(), prefix));
}

/** Пишет файл с содержимым. */
export async function writeFile(dir: string, name: string, content: string): Promise<string> {
  const p = path.join(dir, name);
  await fs.writeFile(p, content, "utf8");
  return p;
}

/** Список файлов в директории. */
export async function ls(dir: string): Promise<string[]> {
  try {
    return (await fs.readdir(dir)).sort();
  } catch {
    return [];
  }
}

/** Базовый валидный конфиг для тестов (dry-run). */
export function baseConfig(overrides: Partial<AppConfig> = {}): AppConfig {
  return {
    downloadDir: "/tmp/dl",
    promptsDir: "/tmp/prompts",
    textsDir: "/tmp/texts",
    proxy: { type: "http", host: "1.2.3.4", port: 8080, login: "u", password: "p", name: "", changeIpUrl: "" },
    proxyString: "",
    google: { email: "a@gmail.com", password: "secret", totpSecret: "", recoveryEmail: "" },
    voiceDesign: {
      model: "eleven_ttv_v3",
      voicesToCreate: 3,
      previewText: "",
      previewToSaveIndex: 0,
      voiceNamePrefix: "AutoVoice",
    },
    tts: {
      model: "eleven_multilingual_v2",
      stability: 0.5,
      similarity: 0.75,
      style: 0,
      speed: 1,
      speakerBoost: true,
      outputFormat: "mp3",
    },
    dolphinApiToken: "token-123",
    dolphinLocalApi: "http://localhost:3001",
    dolphinRemoteApi: "https://dolphin-anty-api.com",
    platform: "windows",
    profileNamePrefix: "EL-Auto",
    reuseProfileId: "",
    loginMethod: "google",
    elevenLabsPassword: "",
    manualAssist: true,
    manualAssistTimeoutSec: 300,
    deleteProfileOnFinish: true,
    consumeTextFiles: true,
    headless: false,
    minCreditsThreshold: 0,
    // По умолчанию ограничение длительности отключено (0/0), чтобы базовые
    // тесты проверяли остальную логику; тесты гейтинга задают пороги явно.
    minDurationSec: 0,
    maxDurationSec: 0,
    dryRun: true,
    ...overrides,
  };
}
