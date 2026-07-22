import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

/**
 * Копирует папку public/, README и .env.example рядом с собранным бинарником,
 * чтобы получилась портативная сборка «распаковал и запустил».
 * Использование: node scripts/copy-assets.mjs <win|mac|linux>
 */
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const target = process.argv[2] || "linux";
const outDir = path.join(root, "release", target);

fs.mkdirSync(outDir, { recursive: true });

function copyDir(src, dest) {
  fs.mkdirSync(dest, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const s = path.join(src, entry.name);
    const d = path.join(dest, entry.name);
    if (entry.isDirectory()) copyDir(s, d);
    else fs.copyFileSync(s, d);
  }
}

copyDir(path.join(root, "public"), path.join(outDir, "public"));
copyDir(path.join(root, "samples"), path.join(outDir, "samples"));
fs.copyFileSync(path.join(root, ".env.example"), path.join(outDir, ".env.example"));
if (fs.existsSync(path.join(root, "README.md"))) {
  fs.copyFileSync(path.join(root, "README.md"), path.join(outDir, "README.md"));
}

console.log(`Ассеты скопированы в ${outDir}`);
