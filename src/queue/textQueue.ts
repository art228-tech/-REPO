import fs from "node:fs/promises";
import path from "node:path";
import { listFiles, pathExists } from "../util/fsUtils.js";

export interface TextItem {
  path: string;
  name: string;
}

const TEXT_EXTENSIONS = [".txt", ".md", ".text"];

/**
 * Очередь текстов для озвучки. Каждый текст используется один раз: после
 * успешной озвучки исходный файл удаляется (если включено consume). Файлы,
 * которые не удалось озвучить, помечаются как проблемные и пропускаются, чтобы
 * не зациклиться.
 */
export class TextQueue {
  private pending: TextItem[] = [];
  private readonly failed = new Set<string>();

  constructor(private readonly dir: string, private readonly consume = true) {}

  /** Загружает список файлов (содержимое читается позже, в момент использования). */
  async load(): Promise<void> {
    const files = await listFiles(this.dir, TEXT_EXTENSIONS);
    this.pending = files.map((file) => ({ path: file, name: path.basename(file) }));
  }

  get remaining(): number {
    return this.pending.length;
  }

  hasNext(): boolean {
    return this.pending.length > 0;
  }

  /** Достаёт следующий текст из очереди (без удаления файла). */
  next(): TextItem | null {
    return this.pending.shift() ?? null;
  }

  /** Читает содержимое текста. Пустые файлы возвращают пустую строку. */
  async readContent(item: TextItem): Promise<string> {
    return (await fs.readFile(item.path, "utf8")).trim();
  }

  /** Отмечает текст как успешно озвученный: удаляет исходный файл при consume. */
  async complete(item: TextItem): Promise<void> {
    if (this.consume && (await pathExists(item.path))) {
      await fs.unlink(item.path);
    }
  }

  /** Помечает текст как проблемный: он не будет использоваться повторно. */
  fail(item: TextItem): void {
    this.failed.add(item.path);
  }

  failedCount(): number {
    return this.failed.size;
  }
}
