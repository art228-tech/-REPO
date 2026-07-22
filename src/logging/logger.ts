import { EventEmitter } from "node:events";
import fs from "node:fs";
import path from "node:path";

export type LogLevel = "debug" | "info" | "warn" | "error" | "success";

export interface LogEntry {
  ts: number;
  level: LogLevel;
  /** Логический этап/подсистема (dolphin, elevenlabs, orchestrator, ...). */
  scope: string;
  message: string;
  /** Дополнительный структурированный контекст. */
  meta?: Record<string, unknown>;
}

const LEVEL_ORDER: Record<LogLevel, number> = {
  debug: 10,
  info: 20,
  success: 25,
  warn: 30,
  error: 40,
};

export interface LoggerOptions {
  /** Директория, куда пишется файл лога текущей сессии. */
  logDir: string;
  /** Минимальный уровень, который сохраняется/эмитится. */
  minLevel?: LogLevel;
  /** Сколько последних записей держать в памяти для UI. */
  bufferSize?: number;
  /** Дублировать в stdout. */
  console?: boolean;
}

/**
 * Централизованный логгер: пишет в файл, хранит кольцевой буфер для UI,
 * эмитит события `entry` для стриминга по WebSocket, и позволяет скачать
 * весь лог сессии одним файлом.
 */
export class Logger extends EventEmitter {
  private readonly logDir: string;
  private minLevel: LogLevel;
  private readonly bufferSize: number;
  private readonly console: boolean;
  private buffer: LogEntry[] = [];
  private stream: fs.WriteStream | null = null;
  private currentFile: string | null = null;

  constructor(options: LoggerOptions) {
    super();
    this.setMaxListeners(0);
    this.logDir = options.logDir;
    this.minLevel = options.minLevel ?? "debug";
    this.bufferSize = options.bufferSize ?? 5000;
    this.console = options.console ?? true;
    fs.mkdirSync(this.logDir, { recursive: true });
  }

  setMinLevel(level: LogLevel): void {
    this.minLevel = level;
  }

  /** Открывает новый файл лога для сессии. Возвращает путь. */
  startSession(sessionId: string): string {
    this.closeSession();
    const safe = sessionId.replace(/[^a-zA-Z0-9_-]/g, "_");
    const file = path.join(this.logDir, `session-${safe}.log`);
    this.currentFile = file;
    this.stream = fs.createWriteStream(file, { flags: "a" });
    this.info("logger", `Начата сессия логирования`, { file });
    return file;
  }

  closeSession(): void {
    if (this.stream) {
      this.stream.end();
      this.stream = null;
    }
  }

  get sessionFile(): string | null {
    return this.currentFile;
  }

  private write(level: LogLevel, scope: string, message: string, meta?: Record<string, unknown>): void {
    if (LEVEL_ORDER[level] < LEVEL_ORDER[this.minLevel]) return;
    const entry: LogEntry = { ts: Date.now(), level, scope, message, meta };

    this.buffer.push(entry);
    if (this.buffer.length > this.bufferSize) {
      this.buffer.splice(0, this.buffer.length - this.bufferSize);
    }

    const line = formatLine(entry);
    if (this.stream) this.stream.write(line + "\n");
    if (this.console) {
      const consoleFn = level === "error" ? console.error : level === "warn" ? console.warn : console.log;
      consoleFn(line);
    }
    this.emit("entry", entry);
  }

  debug(scope: string, message: string, meta?: Record<string, unknown>): void {
    this.write("debug", scope, message, meta);
  }
  info(scope: string, message: string, meta?: Record<string, unknown>): void {
    this.write("info", scope, message, meta);
  }
  success(scope: string, message: string, meta?: Record<string, unknown>): void {
    this.write("success", scope, message, meta);
  }
  warn(scope: string, message: string, meta?: Record<string, unknown>): void {
    this.write("warn", scope, message, meta);
  }
  error(scope: string, message: string, meta?: Record<string, unknown>): void {
    this.write("error", scope, message, meta);
  }

  /** Возвращает последние N записей (для первичной отрисовки в UI). */
  recent(limit = 500): LogEntry[] {
    return this.buffer.slice(-limit);
  }

  /** Полный текст лога сессии (для скачивания). */
  dumpText(): string {
    return this.buffer.map(formatLine).join("\n") + "\n";
  }

  clearBuffer(): void {
    this.buffer = [];
  }
}

/** Возвращает читаемую строку лога с маскировкой секретов в meta. */
export function formatLine(entry: LogEntry): string {
  const time = new Date(entry.ts).toISOString();
  const level = entry.level.toUpperCase().padEnd(7);
  let line = `[${time}] ${level} (${entry.scope}) ${entry.message}`;
  if (entry.meta && Object.keys(entry.meta).length > 0) {
    line += ` ${JSON.stringify(maskSecrets(entry.meta))}`;
  }
  return line;
}

const SECRET_KEYS = /(password|pass|token|secret|apikey|api_key|authorization|cookie)/i;

/** Маскирует значения потенциально секретных ключей, чтобы не утекали в логи. */
export function maskSecrets(meta: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(meta)) {
    if (SECRET_KEYS.test(k) && typeof v === "string" && v.length > 0) {
      out[k] = maskValue(v);
    } else if (v && typeof v === "object" && !Array.isArray(v)) {
      out[k] = maskSecrets(v as Record<string, unknown>);
    } else {
      out[k] = v;
    }
  }
  return out;
}

function maskValue(value: string): string {
  if (value.length <= 4) return "****";
  return `${value.slice(0, 2)}***${value.slice(-2)}`;
}
