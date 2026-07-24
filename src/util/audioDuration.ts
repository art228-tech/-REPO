import { Logger } from "../logging/logger.js";

/**
 * Возвращает длительность аудиофайла в секундах, либо null, если определить
 * не удалось. Использует music-metadata (mp3/wav/ogg/…). Импорт динамический,
 * чтобы работать и в ESM (tsx), и в собранном CJS-бандле (pkg).
 */
export async function getAudioDurationSec(filePath: string, logger?: Logger): Promise<number | null> {
  try {
    const [{ readFile }, mm] = await Promise.all([import("node:fs/promises"), import("music-metadata")]);
    const buffer = await readFile(filePath);
    const metadata = await mm.parseBuffer(new Uint8Array(buffer), undefined, { duration: true });
    const duration = metadata.format?.duration;
    if (typeof duration === "number" && Number.isFinite(duration) && duration > 0) {
      return duration;
    }
    logger?.warn("audio", "Не удалось определить длительность (нет duration в метаданных)", { filePath });
    return null;
  } catch (error) {
    logger?.warn("audio", "Ошибка чтения длительности аудио", {
      filePath,
      error: error instanceof Error ? error.message : String(error),
    });
    return null;
  }
}

export type DurationVerdict = "ok" | "too_short" | "too_long" | "unknown";

/**
 * Проверяет длительность относительно порогов. Пороги <= 0 означают
 * «без ограничения». Неизвестная длительность (null) считается допустимой
 * (не отбраковываем то, что не смогли измерить).
 */
export function checkDuration(durationSec: number | null, minSec: number, maxSec: number): DurationVerdict {
  if (durationSec === null) return "unknown";
  if (minSec > 0 && durationSec < minSec) return "too_short";
  if (maxSec > 0 && durationSec > maxSec) return "too_long";
  return "ok";
}
