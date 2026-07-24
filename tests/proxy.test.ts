import { describe, expect, it } from "vitest";
import { formatProxyString, parseProxyString } from "../src/util/proxy.js";
import { validateConfig } from "../src/config/schema.js";
import { baseConfig } from "./helpers.js";

describe("parseProxyString", () => {
  it("host:port:login:password", () => {
    expect(parseProxyString("185.240.93.75:8000:kekTAz:MvaYkY")).toEqual({
      type: undefined,
      host: "185.240.93.75",
      port: 8000,
      login: "kekTAz",
      password: "MvaYkY",
    });
  });

  it("host:port без авторизации", () => {
    expect(parseProxyString("1.2.3.4:8080")).toEqual({
      type: undefined,
      host: "1.2.3.4",
      port: 8080,
      login: "",
      password: "",
    });
  });

  it("login:password@host:port", () => {
    expect(parseProxyString("user:pass@1.2.3.4:3128")).toMatchObject({
      host: "1.2.3.4",
      port: 3128,
      login: "user",
      password: "pass",
    });
  });

  it("scheme://... задаёт тип", () => {
    expect(parseProxyString("socks5://1.2.3.4:1080:u:p")).toMatchObject({
      type: "socks5",
      host: "1.2.3.4",
      port: 1080,
      login: "u",
      password: "p",
    });
  });

  it("пароль с двоеточием сохраняется целиком", () => {
    expect(parseProxyString("1.2.3.4:8080:user:pa:ss:word").password).toBe("pa:ss:word");
  });

  it("бросает на строке без порта", () => {
    expect(() => parseProxyString("just-a-host")).toThrow();
  });

  it("бросает на неверном порту", () => {
    expect(() => parseProxyString("1.2.3.4:99999")).toThrow();
  });
});

describe("formatProxyString", () => {
  it("собирает строку обратно", () => {
    expect(formatProxyString({ host: "1.2.3.4", port: 8080, login: "u", password: "p" })).toBe("1.2.3.4:8080:u:p");
    expect(formatProxyString({ host: "1.2.3.4", port: 8080 })).toBe("1.2.3.4:8080");
  });
});

describe("validateConfig: нормализация proxyString", () => {
  it("разбирает proxyString и заполняет proxy при пустом host", () => {
    const cfg = baseConfig({
      proxyString: "185.240.93.75:8000:kekTAz:MvaYkY",
      proxy: { type: "http", host: "", port: 8080, login: "", password: "", name: "", changeIpUrl: "" },
    });
    const r = validateConfig(cfg);
    expect(r.ok).toBe(true);
    expect(r.config?.proxy).toMatchObject({
      host: "185.240.93.75",
      port: 8000,
      login: "kekTAz",
      password: "MvaYkY",
    });
  });

  it("тип из scheme в строке перекрывает выбранный", () => {
    const cfg = baseConfig({
      proxyString: "socks5://9.9.9.9:1080",
      proxy: { type: "http", host: "", port: 1, login: "", password: "", name: "", changeIpUrl: "" },
    });
    const r = validateConfig(cfg);
    expect(r.ok).toBe(true);
    expect(r.config?.proxy.type).toBe("socks5");
  });

  it("невалидная строка прокси → ошибка на proxyString", () => {
    const cfg = baseConfig({ proxyString: "broken", proxy: { type: "http", host: "", port: 8080, login: "", password: "", name: "", changeIpUrl: "" } });
    const r = validateConfig(cfg);
    expect(r.ok).toBe(false);
    expect(r.errors?.some((e) => e.path === "proxyString")).toBe(true);
  });

  it("без proxyString используется структурный proxy как раньше", () => {
    const r = validateConfig(baseConfig());
    expect(r.ok).toBe(true);
    expect(r.config?.proxy.host).toBe("1.2.3.4");
  });
});
