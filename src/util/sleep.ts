/** Пауза на указанное число миллисекунд. */
export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Случайная человекоподобная пауза в диапазоне [minMs, maxMs]. */
export function humanDelay(minMs = 400, maxMs = 1200): Promise<void> {
  const ms = Math.floor(minMs + Math.random() * Math.max(0, maxMs - minMs));
  return sleep(ms);
}
