import crypto from "node:crypto";

/** Декодирует Base32 (RFC 4648) в Buffer. */
function base32Decode(input: string): Buffer {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  const clean = input.replace(/=+$/g, "").replace(/\s+/g, "").toUpperCase();
  let bits = 0;
  let value = 0;
  const bytes: number[] = [];
  for (const char of clean) {
    const idx = alphabet.indexOf(char);
    if (idx === -1) continue;
    value = (value << 5) | idx;
    bits += 5;
    if (bits >= 8) {
      bytes.push((value >>> (bits - 8)) & 0xff);
      bits -= 8;
    }
  }
  return Buffer.from(bytes);
}

/**
 * Генерирует TOTP-код (RFC 6238) из Base32-секрета. Используется для входа
 * в Google-аккаунты с включённой 2FA. По умолчанию SHA-1, 6 цифр, шаг 30с.
 */
export function generateTotp(secret: string, timeStepSec = 30, digits = 6, forTime = Date.now()): string {
  const key = base32Decode(secret);
  const counter = Math.floor(forTime / 1000 / timeStepSec);
  const buf = Buffer.alloc(8);
  buf.writeBigUInt64BE(BigInt(counter));
  const hmac = crypto.createHmac("sha1", key).update(buf).digest();
  const offset = hmac[hmac.length - 1] & 0x0f;
  const binary =
    ((hmac[offset] & 0x7f) << 24) |
    ((hmac[offset + 1] & 0xff) << 16) |
    ((hmac[offset + 2] & 0xff) << 8) |
    (hmac[offset + 3] & 0xff);
  const otp = binary % 10 ** digits;
  return otp.toString().padStart(digits, "0");
}
