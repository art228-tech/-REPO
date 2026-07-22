import { afterEach, describe, expect, it } from "vitest";
import fs from "node:fs/promises";
import { PromptQueue } from "../src/queue/promptQueue.js";
import { TextQueue } from "../src/queue/textQueue.js";
import { ls, tmpDir, writeFile } from "./helpers.js";

const dirs: string[] = [];
async function make(): Promise<string> {
  const d = await tmpDir();
  dirs.push(d);
  return d;
}
afterEach(async () => {
  for (const d of dirs.splice(0)) await fs.rm(d, { recursive: true, force: true });
});

describe("PromptQueue", () => {
  it("читает непустые файлы и отдаёт их по кругу", async () => {
    const dir = await make();
    await writeFile(dir, "1.txt", "первый промпт голоса");
    await writeFile(dir, "2.txt", "второй промпт голоса");
    await writeFile(dir, "empty.txt", "   ");

    const q = new PromptQueue(dir);
    await q.load();
    expect(q.size).toBe(2);

    const seen = [q.next().content, q.next().content, q.next().content, q.next().content];
    expect(seen[0]).toBe("первый промпт голоса");
    expect(seen[1]).toBe("второй промпт голоса");
    // цикл: снова первый, затем второй
    expect(seen[2]).toBe("первый промпт голоса");
    expect(seen[3]).toBe("второй промпт голоса");
  });

  it("бросает при пустой папке", async () => {
    const dir = await make();
    const q = new PromptQueue(dir);
    await q.load();
    expect(q.isEmpty()).toBe(true);
    expect(() => q.next()).toThrow();
  });
});

describe("TextQueue", () => {
  it("выдаёт тексты по одному и удаляет после complete", async () => {
    const dir = await make();
    await writeFile(dir, "a.txt", "текст А");
    await writeFile(dir, "b.txt", "текст Б");

    const q = new TextQueue(dir, true);
    await q.load();
    expect(q.remaining).toBe(2);

    const a = q.next()!;
    expect(await q.readContent(a)).toBe("текст А");
    await q.complete(a);
    expect(await ls(dir)).toEqual(["b.txt"]);

    const b = q.next()!;
    await q.complete(b);
    expect(await ls(dir)).toEqual([]);
    expect(q.hasNext()).toBe(false);
  });

  it("не удаляет файлы, если consume=false", async () => {
    const dir = await make();
    await writeFile(dir, "a.txt", "текст");
    const q = new TextQueue(dir, false);
    await q.load();
    const a = q.next()!;
    await q.complete(a);
    expect(await ls(dir)).toEqual(["a.txt"]);
  });

  it("fail помечает файл и не удаляет его", async () => {
    const dir = await make();
    await writeFile(dir, "a.txt", "текст");
    const q = new TextQueue(dir, true);
    await q.load();
    const a = q.next()!;
    q.fail(a);
    expect(q.failedCount()).toBe(1);
    expect(await ls(dir)).toEqual(["a.txt"]);
  });
});
