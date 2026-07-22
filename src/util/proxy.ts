export interface ParsedProxy {
  type?: "http" | "socks4" | "socks5" | "ssh";
  host: string;
  port: number;
  login: string;
  password: string;
}

const SCHEME_MAP: Record<string, ParsedProxy["type"]> = {
  http: "http",
  https: "http",
  socks: "socks5",
  socks4: "socks4",
  socks5: "socks5",
  ssh: "ssh",
};

/**
 * Разбирает строку прокси в структурированный вид. Поддерживаются форматы:
 *   host:port
 *   host:port:login:password
 *   login:password@host:port
 *   scheme://host:port[:login:password]  (scheme: http/https/socks4/socks5/ssh)
 *   scheme://login:password@host:port
 * Пароль может содержать двоеточия (для colon-формата берётся всё после 3-го «:»).
 */
export function parseProxyString(raw: string): ParsedProxy {
  let s = (raw ?? "").trim();
  if (!s) throw new Error("Пустая строка прокси");

  let type: ParsedProxy["type"] | undefined;
  const schemeMatch = s.match(/^([a-zA-Z][a-zA-Z0-9]*):\/\//);
  if (schemeMatch) {
    type = SCHEME_MAP[schemeMatch[1].toLowerCase()];
    s = s.slice(schemeMatch[0].length);
  }

  let login = "";
  let password = "";
  let hostPort = s;

  if (s.includes("@")) {
    // Формат login:password@host:port
    const at = s.lastIndexOf("@");
    const creds = s.slice(0, at);
    hostPort = s.slice(at + 1);
    const ci = creds.indexOf(":");
    if (ci === -1) {
      login = creds;
    } else {
      login = creds.slice(0, ci);
      password = creds.slice(ci + 1);
    }
    const { host, port } = splitHostPort(hostPort);
    return finalize({ type, host, port, login, password });
  }

  // Colon-формат: host:port[:login:password]
  const parts = s.split(":");
  if (parts.length < 2) {
    throw new Error("Неверный формат прокси. Ожидается host:port или host:port:login:password");
  }
  const host = parts[0].trim();
  const port = toPort(parts[1]);
  if (parts.length >= 4) {
    login = parts[2];
    password = parts.slice(3).join(":");
  } else if (parts.length === 3) {
    login = parts[2];
  }
  return finalize({ type, host, port, login, password });
}

function splitHostPort(hostPort: string): { host: string; port: number } {
  const idx = hostPort.lastIndexOf(":");
  if (idx === -1) throw new Error("В строке прокси не указан порт (host:port)");
  return { host: hostPort.slice(0, idx).trim(), port: toPort(hostPort.slice(idx + 1)) };
}

function toPort(value: string): number {
  const port = Number(String(value).trim());
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error(`Неверный порт прокси: "${value}"`);
  }
  return port;
}

function finalize(p: ParsedProxy): ParsedProxy {
  if (!p.host) throw new Error("В строке прокси не указан host");
  return { type: p.type, host: p.host, port: p.port, login: p.login ?? "", password: p.password ?? "" };
}

/** Собирает строку прокси обратно (host:port[:login:password]) для отображения. */
export function formatProxyString(p: {
  host?: string;
  port?: number | string;
  login?: string;
  password?: string;
}): string {
  if (!p.host || !p.port) return "";
  const base = `${p.host}:${p.port}`;
  if (p.login) {
    return `${base}:${p.login}:${p.password ?? ""}`;
  }
  return base;
}
