import { describe, expect, it } from "vitest";
import { generateTotp } from "../src/elevenlabs/totp.js";

// RFC 6238 test vector (SHA-1, секрет ASCII "12345678901234567890").
const SECRET_BASE32 = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ";

describe("generateTotp", () => {
  it("совпадает с эталонным вектором RFC 6238 (T=59)", () => {
    expect(generateTotp(SECRET_BASE32, 30, 6, 59 * 1000)).toBe("287082");
  });

  it("совпадает с эталонным вектором RFC 6238 (T=1111111109)", () => {
    expect(generateTotp(SECRET_BASE32, 30, 6, 1111111109 * 1000)).toBe("081804");
  });

  it("возвращает 6 цифр", () => {
    expect(generateTotp(SECRET_BASE32)).toMatch(/^\d{6}$/);
  });
});
