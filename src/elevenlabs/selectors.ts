/**
 * Централизованный список селекторов. UI ElevenLabs и Google периодически
 * меняется, поэтому для каждого действия хранится НЕСКОЛЬКО кандидатов и
 * текстовых меток — хелперы перебирают их по очереди. Если что-то сломалось,
 * достаточно поправить селекторы здесь, не трогая логику.
 */
export const GOOGLE_SELECTORS = {
  emailInput: ['input[type="email"]', "#identifierId", 'input[name="identifier"]'],
  emailNextText: ["Далее", "Next"],
  passwordInput: ['input[type="password"]', 'input[name="Passwd"]', 'input[name="password"]'],
  passwordNextText: ["Далее", "Next"],
  totpInput: ['input[name="totpPin"]', "#totpPin", 'input[type="tel"]'],
  approveButtonText: ["Продолжить", "Continue", "Разрешить", "Allow"],
};

export const ELEVENLABS_SELECTORS = {
  /** Кнопки/ссылки входа через Google на странице sign-in. */
  googleSignInText: [
    "Continue with Google",
    "Sign in with Google",
    "Продолжить с Google",
    "Войти через Google",
    "Google",
  ],
  googleSignInButton: [
    'button[data-provider="google"]',
    'a[href*="google"]',
    'button:has(img[alt*="Google"])',
  ],

  /** Признак успешного входа: наличие сайдбара/навигации приложения. */
  loggedInMarkers: ['nav[aria-label]', '[data-testid="sidebar"]', 'a[href*="/app/"]'],

  /** Voice Design. */
  voiceDesignEntryText: ["Voice Design", "Design", "Создать голос", "Дизайн голоса"],
  voiceDescriptionTextarea: [
    'textarea[placeholder*="describe" i]',
    'textarea[placeholder*="voice" i]',
    'textarea[name*="description" i]',
    "textarea",
  ],
  previewTextarea: [
    'textarea[placeholder*="preview" i]',
    'textarea[placeholder*="text to preview" i]',
  ],
  generateButtonText: ["Generate", "Generate voices", "Сгенерировать", "Создать"],
  previewCandidate: [
    '[data-testid*="preview"]',
    '[role="radio"]',
    '[data-preview-index]',
  ],
  saveVoiceButtonText: ["Save voice", "Save", "Add to library", "Сохранить", "Сохранить голос"],
  voiceNameInput: [
    'input[placeholder*="name" i]',
    'input[name*="name" i]',
    'input[aria-label*="name" i]',
  ],
  confirmSaveButtonText: ["Save", "Confirm", "Create voice", "Сохранить", "Создать"],

  /** Text to Speech. */
  ttsTextarea: [
    'textarea[placeholder*="text" i]',
    'div[contenteditable="true"]',
    "textarea",
  ],
  voiceSelector: [
    '[data-testid="voice-selector"]',
    'button[aria-haspopup="listbox"]',
    'button[aria-label*="voice" i]',
  ],
  generateSpeechButtonText: ["Generate speech", "Generate", "Сгенерировать речь", "Сгенерировать"],
  downloadButtonText: ["Download", "Скачать", "Export"],
  settingsToggleText: ["Settings", "Voice settings", "Настройки"],

  /** Индикатор остатка кредитов (символов). */
  creditsMarkers: [
    '[data-testid="character-count"]',
    '[data-testid="subscription-usage"]',
    'text/credits remaining',
  ],

  /** Тексты ошибки лимита кредитов. */
  outOfCreditsText: [
    "out of credits",
    "quota exceeded",
    "not enough credits",
    "insufficient",
    "недостаточно",
    "лимит",
    "закончились",
  ],
};
