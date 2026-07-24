import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { DolphinLocalApi } from "../src/dolphin/localApi.js";
import { DolphinRemoteApi } from "../src/dolphin/remoteApi.js";
import { Logger } from "../src/logging/logger.js";

function makeLogger(): Logger {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ellog-"));
  return new Logger({ logDir: dir, console: false });
}

function mockResponse(body: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    text: async () => (typeof body === "string" ? body : JSON.stringify(body)),
  } as Response;
}

const logger = makeLogger();

afterEach(() => vi.restoreAllMocks());

describe("DolphinRemoteApi.buildProfilePayload", () => {
  it("встраивает прокси и user-agent в payload", () => {
    const api = new DolphinRemoteApi("https://x", "tok", logger);
    const payload = api.buildProfilePayload(
      {
        name: "P1",
        platform: "windows",
        proxy: { type: "socks5", host: "9.9.9.9", port: 1080, login: "u", password: "p", name: "", changeIpUrl: "" },
      },
      "Mozilla/5.0 UA",
    ) as any;
    expect(payload.name).toBe("P1");
    expect(payload.useragent.value).toBe("Mozilla/5.0 UA");
    expect(payload.proxy).toMatchObject({ type: "socks5", host: "9.9.9.9", port: 1080, login: "u", password: "p" });
  });
});

describe("DolphinRemoteApi.createProfile", () => {
  it("парсит id из разных форм ответа", async () => {
    const api = new DolphinRemoteApi("https://api", "tok", logger);
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if ((init?.method ?? "GET") === "GET") return mockResponse({ data: [{ value: "Mozilla/5.0 UA" }] });
      return mockResponse({ browserProfileId: 777 });
    });
    vi.stubGlobal("fetch", fetchMock as unknown as typeof fetch);

    const id = await api.createProfile({
      name: "P",
      platform: "windows",
      proxy: { type: "http", host: "1.1.1.1", port: 80, login: "", password: "", name: "", changeIpUrl: "" },
    });
    expect(id).toBe("777");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("использует дефолтный UA, если запрос UA упал", async () => {
    const api = new DolphinRemoteApi("https://api", "tok", logger);
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      if ((init?.method ?? "GET") === "GET") throw new Error("network");
      return mockResponse({ data: { id: 5 } });
    });
    vi.stubGlobal("fetch", fetchMock as unknown as typeof fetch);
    const id = await api.createProfile({
      name: "P",
      platform: "windows",
      proxy: { type: "http", host: "1.1.1.1", port: 80, login: "", password: "", name: "", changeIpUrl: "" },
    });
    expect(id).toBe("5");
  });

  it("бросает на HTTP-ошибке", async () => {
    const api = new DolphinRemoteApi("https://api", "tok", logger);
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init?: RequestInit) => {
        if ((init?.method ?? "GET") === "GET") return mockResponse({ data: [] });
        return mockResponse("bad request", false, 400);
      }) as unknown as typeof fetch,
    );
    await expect(
      api.createProfile({
        name: "P",
        platform: "windows",
        proxy: { type: "http", host: "1.1.1.1", port: 80, login: "", password: "", name: "", changeIpUrl: "" },
      }),
    ).rejects.toThrow();
  });
});

describe("DolphinRemoteApi.deleteProfile", () => {
  it("успех при 200", async () => {
    const api = new DolphinRemoteApi("https://api", "tok", logger);
    vi.stubGlobal("fetch", vi.fn(async () => mockResponse({ success: true })) as unknown as typeof fetch);
    await expect(api.deleteProfile("1")).resolves.toBeUndefined();
  });

  it("не бросает при 404 (профиль уже удалён)", async () => {
    const api = new DolphinRemoteApi("https://api", "tok", logger);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => mockResponse({ success: false, error: { code: "E_BROWSER_PROFILE_NOT_FOUND" } }, false, 404)) as unknown as typeof fetch,
    );
    await expect(api.deleteProfile("1")).resolves.toBeUndefined();
  });
});

describe("DolphinLocalApi.startProfile", () => {
  it("парсит port и wsEndpoint", async () => {
    const api = new DolphinLocalApi("http://localhost:3001", logger);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => mockResponse({ automation: { port: 50568, wsEndpoint: "/devtools/browser/abc" } })) as unknown as typeof fetch,
    );
    const ep = await api.startProfile("pid", false);
    expect(ep.port).toBe(50568);
    expect(ep.wsEndpoint).toBe("/devtools/browser/abc");
  });

  it("бросает, если нет port/wsEndpoint", async () => {
    const api = new DolphinLocalApi("http://localhost:3001", logger);
    vi.stubGlobal("fetch", vi.fn(async () => mockResponse({ success: true })) as unknown as typeof fetch);
    await expect(api.startProfile("pid", false)).rejects.toThrow();
  });
});
