import { describe, expect, it } from "vitest";
import { describeError } from "../src/util/net.js";

describe("describeError", () => {
  it("извлекает код причины (cause.code)", () => {
    const err = new TypeError("fetch failed");
    (err as any).cause = { code: "ETIMEDOUT" };
    expect(describeError(err)).toBe("fetch failed (ETIMEDOUT)");
  });

  it("извлекает код из cause.errors[0]", () => {
    const err = new TypeError("fetch failed");
    (err as any).cause = { errors: [{ code: "ENOTFOUND" }] };
    expect(describeError(err)).toBe("fetch failed (ENOTFOUND)");
  });

  it("распознаёт таймаут (AbortError)", () => {
    const err = new Error("aborted");
    err.name = "AbortError";
    expect(describeError(err)).toBe("таймаут запроса");
  });

  it("возвращает сообщение без причины", () => {
    expect(describeError(new Error("boom"))).toBe("boom");
  });
});
