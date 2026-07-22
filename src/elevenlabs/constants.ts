/** Ограничения и константы ElevenLabs, критичные для стабильности. */
export const ELEVENLABS = {
  APP_URL: "https://elevenlabs.io/app/home",
  SIGN_IN_URL: "https://elevenlabs.io/app/sign-in",
  VOICE_DESIGN_URL: "https://elevenlabs.io/app/voice-lab",
  TTS_URL: "https://elevenlabs.io/app/speech-synthesis/text-to-speech",
  USAGE_URL: "https://elevenlabs.io/app/usage",

  /** Описание голоса (Voice Design): 20..1000 символов. */
  VOICE_DESCRIPTION_MIN: 20,
  VOICE_DESCRIPTION_MAX: 1000,
  /** Текст-превью голоса: 100..1000 символов. */
  PREVIEW_TEXT_MIN: 100,
  PREVIEW_TEXT_MAX: 1000,
  /** Voice Design генерирует 3 превью-кандидата. */
  PREVIEW_CANDIDATES: 3,

  /** Максимум символов в поле TTS за одну генерацию (безопасный предел). */
  TTS_MAX_CHARS: 5000,
} as const;

export interface PromptValidationResult {
  ok: boolean;
  /** Итоговый (возможно, обрезанный) текст, пригодный к отправке. */
  value: string;
  /** Причина отбраковки или предупреждение. */
  reason?: string;
  /** Был ли текст обрезан по верхней границе. */
  truncated: boolean;
}

/**
 * Проверяет и нормализует описание голоса под лимиты ElevenLabs.
 * Слишком короткие описания отбраковываются (голос не создастся),
 * слишком длинные — безопасно обрезаются по границе слова.
 */
export function validateVoiceDescription(raw: string): PromptValidationResult {
  const value = raw.trim().replace(/\s+/g, " ");
  if (value.length < ELEVENLABS.VOICE_DESCRIPTION_MIN) {
    return {
      ok: false,
      value,
      truncated: false,
      reason: `Описание голоса слишком короткое (${value.length} симв.), минимум ${ELEVENLABS.VOICE_DESCRIPTION_MIN}`,
    };
  }
  if (value.length > ELEVENLABS.VOICE_DESCRIPTION_MAX) {
    return {
      ok: true,
      value: truncateAtWord(value, ELEVENLABS.VOICE_DESCRIPTION_MAX),
      truncated: true,
      reason: `Описание длиннее ${ELEVENLABS.VOICE_DESCRIPTION_MAX} симв. — обрезано, чтобы избежать ошибки лимита`,
    };
  }
  return { ok: true, value, truncated: false };
}

/**
 * Нормализует текст-превью. Если пусто — возвращает ok:false с пометкой,
 * что превью нужно генерировать автоматически (ElevenLabs это поддерживает).
 */
export function validatePreviewText(raw: string): PromptValidationResult {
  const value = raw.trim().replace(/\s+/g, " ");
  if (value.length === 0) {
    return { ok: false, value: "", truncated: false, reason: "Пустой preview — используем авто-генерацию" };
  }
  if (value.length < ELEVENLABS.PREVIEW_TEXT_MIN) {
    return {
      ok: false,
      value,
      truncated: false,
      reason: `Preview короче ${ELEVENLABS.PREVIEW_TEXT_MIN} симв. — используем авто-генерацию`,
    };
  }
  if (value.length > ELEVENLABS.PREVIEW_TEXT_MAX) {
    return {
      ok: true,
      value: truncateAtWord(value, ELEVENLABS.PREVIEW_TEXT_MAX),
      truncated: true,
      reason: `Preview длиннее ${ELEVENLABS.PREVIEW_TEXT_MAX} симв. — обрезан`,
    };
  }
  return { ok: true, value, truncated: false };
}

/** Обрезает строку по границе слова не длиннее max символов. */
export function truncateAtWord(text: string, max: number): string {
  if (text.length <= max) return text;
  const slice = text.slice(0, max);
  const lastSpace = slice.lastIndexOf(" ");
  return (lastSpace > max * 0.6 ? slice.slice(0, lastSpace) : slice).trim();
}

/**
 * Разбивает длинный текст озвучки на части не длиннее maxChars, стараясь
 * резать по границам предложений/абзацев.
 */
export function chunkText(text: string, maxChars: number = ELEVENLABS.TTS_MAX_CHARS): string[] {
  const clean = text.trim();
  if (clean.length <= maxChars) return clean.length ? [clean] : [];

  const chunks: string[] = [];
  const sentences = clean.split(/(?<=[.!?…\n])\s+/);
  let current = "";
  for (const sentence of sentences) {
    if (sentence.length > maxChars) {
      if (current) {
        chunks.push(current.trim());
        current = "";
      }
      for (let i = 0; i < sentence.length; i += maxChars) {
        chunks.push(sentence.slice(i, i + maxChars).trim());
      }
      continue;
    }
    if ((current + " " + sentence).trim().length > maxChars) {
      chunks.push(current.trim());
      current = sentence;
    } else {
      current = current ? `${current} ${sentence}` : sentence;
    }
  }
  if (current.trim()) chunks.push(current.trim());
  return chunks.filter((c) => c.length > 0);
}
