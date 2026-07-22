import path from "node:path";
import { fileURLToPath } from "node:url";
import { ConfigStore } from "./config/store.js";
import { validateConfig } from "./config/schema.js";
import { Orchestrator } from "./core/orchestrator.js";
import { Logger } from "./logging/logger.js";
import { loadDotEnv, resolvePaths } from "./server/env.js";

/**
 * CLI-режим: запускает сценарий по сохранённому конфигу без веб-интерфейса.
 * Флаг --dry-run форсирует симуляцию.
 */
async function main(): Promise<void> {
  const __dirname = path.dirname(fileURLToPath(import.meta.url));
  const root = path.resolve(__dirname, "..");
  loadDotEnv(root);
  const paths = resolvePaths(root);

  const logger = new Logger({ logDir: paths.logDir, console: true });
  const store = new ConfigStore(paths.dataDir);
  const raw = await store.load();
  if (process.argv.includes("--dry-run")) raw.dryRun = true;

  const result = validateConfig(raw);
  if (!result.ok) {
    logger.error("cli", "Конфигурация невалидна — заполните её через UI (npm run dev)", {
      errors: result.errors,
    });
    process.exit(1);
  }

  const orchestrator = new Orchestrator(logger);
  const status = await orchestrator.run(result.config!);
  logger.info("cli", "Готово", { state: status.state, files: status.filesDone });
  process.exit(status.state === "error" ? 1 : 0);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
