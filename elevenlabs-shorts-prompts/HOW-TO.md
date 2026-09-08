# Как пользоваться паком

## Куда вставлять

1. ElevenLabs → **Voices** → **My Voices** → **Add a new voice** → **Voice Design**
2. В поле **Prompt** вставь блок `VOICE DESIGN PROMPT`
3. В поле **Text to preview** вставь блок `TEXT TO PREVIEW` из того же файла
4. **Guidance Scale:** значение из карточки (обычно 28–35)
5. **Loudness:** чуть выше середины, чтобы голос читался в Recs / Shorts
6. Generate → получишь 3 превью → сохрани лучший слот

После сохранения голоса:

- Модель: **Eleven v3** (эмоции и теги) или **Multilingual v2** (стабильнее на длинных русских текстах)
- Скрипты для озвучки лежат в `tts-scripts-v3/`

## Почему так написано

Промпты собраны по официальному шаблону ElevenLabs Voice Design:

```
Native <Language>. <Gender>, <Age range>. <Quality level>.
Persona: <2–5 words>. Emotion: <2–3 adjectives>.
<1–2 sentences about timbre, pacing, delivery>
```

Официальный гайд: https://elevenlabs.io/docs/eleven-creative/voices/voice-design  
Политика: https://elevenlabs.io/use-policy

## Что сознательно НЕ стоит в промптах

- Имена блогеров, актёров, политиков, «как у …»
- teen / подросток / школьник / ребёнок
- «клонируй», «скопируй голос», «знаменитость»
- сексуализация, ASMR-стоны, грубый NSFW
- названия платформ внутри самого промпта (TikTok / YouTube) — чтобы не цеплять фильтры; вайб short-формата описан через pacing и persona

Возраст везде: **young adult, 22–26**. Это взрослый голос, молодой как у ведущих коротких вертикальных видео, но не несовершеннолетний.

## Если генерация отклонилась

1. Возьми файл из `voice-design/compact/` — они короче
2. Убери из превью CAPS и слишком много `!`
3. Guidance опусти до 22–25
4. Не добавляй свои «как у [имя]» — это как раз ломает правила
