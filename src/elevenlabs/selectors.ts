/**
 * Централизованный список селекторов. UI ElevenLabs и Google периодически
 * меняется, поэтому для каждого действия хранится НЕСКОЛЬКО кандидатов и
 * текстовых меток — хелперы перебирают их по очереди. Если что-то сломалось,
 * достаточно поправить селекторы здесь, не трогая логику.
 */
export const GOOGLE_SELECTORS = {
  emailInput: [
    'input[type="email"]',
    "#identifierId",
    'input[name="identifier"]',
    'input[autocomplete="username"]',
    'input[aria-label*="email" i]',
    'input[aria-label*="почт" i]',
    'input[jsname][type="text"]',
  ],
  emailNextText: ["Далее", "Next", "Продолжить", "Continue"],
  passwordInput: [
    'input[type="password"]',
    'input[name="Passwd"]',
    'input[name="password"]',
    'input[autocomplete="current-password"]',
    'input[aria-label*="password" i]',
    'input[aria-label*="пароль" i]',
  ],
  passwordNextText: ["Далее", "Next", "Продолжить", "Continue"],
  totpInput: ['input[name="totpPin"]', "#totpPin", 'input[type="tel"]', 'input[autocomplete="one-time-code"]'],
  approveButtonText: ["Продолжить", "Continue", "Разрешить", "Allow", "Подтвердить", "Confirm"],
  /** Признаки экрана проверки (reCAPTCHA / «Verify it's you» / 2FA) — требуют ручного действия. */
  challengeText: [
    "verify it's you",
    "verify it’s you",
    "i'm not a robot",
    "i’m not a robot",
    "confirm you're not a robot",
    "recaptcha",
    "2-step verification",
    "2-step",
    "enter the code",
    "подтвердите, что это вы",
    "подтвердите, что вы не робот",
    "я не робот",
    "двухэтап",
    "введите код",
  ],

  /** Признаки блокировки автоматизированного входа со стороны Google. */
  blockedText: [
    "couldn't sign you in",
    "couldn’t sign you in",
    "this browser or app may not be secure",
    "не удалось выполнить вход",
    "этот браузер или приложение",
    "browser or app may not be secure",
    "try using a different browser",
  ],
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

  /** Кнопки принятия cookie (Cookiebot и общие). */
  cookieAcceptSelectors: [
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    "#CybotCookiebotDialogBodyButtonAccept",
    "#CybotCookiebotDialogBodyLevelButtonAccept",
    'button[aria-label*="accept" i]',
    'button[id*="accept" i]',
  ],
  cookieAcceptText: [
    "Accept all cookies",
    "Accept all",
    "Allow all",
    "Accept cookies",
    "Принять все",
    "Разрешить все",
    "Принять",
    "Accept",
  ],

  /** Онбординг: выбор платформы и переход дальше. */
  onboardingPlatformText: ["ElevenCreative", "Text to Speech", "Creative"],
  onboardingContinueText: [
    "Continue",
    "Get started",
    "Get Started",
    "Let's go",
    "Next",
    "Skip",
    "Skip for now",
    "Done",
    "Finish",
    "Продолжить",
    "Начать",
    "Далее",
    "Пропустить",
    "Готово",
  ],

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
