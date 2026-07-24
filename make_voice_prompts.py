#!/usr/bin/env python3
"""Generate 12 ElevenLabs Voice Design prompts as .txt files.

Based on the user's reference prompt (young male, energetic YouTuber
style), with slightly faster pacing. Prompts follow ElevenLabs Voice
Design guidance: explicit pacing, audio-quality descriptor, 20-1000
chars, some in the recommended structured format.

Note: no minor-age wording (16-18, teenage, adolescent) - such
descriptions are blocked by the ElevenLabs Prohibited Use Policy.
The youthful sound is conveyed via "young adult", "early 20s" and
timbre descriptors instead.
"""
import os
import re
import sys

BANNED_RE = re.compile(r"16|17|18|teen|adolescen|boy|minor|school", re.IGNORECASE)

PROMPTS = [
    "Young adult male voice in his early 20s, youthful and fresh-sounding, charismatic and energetic, very fast-paced natural speech, neutral American accent, clean pronunciation, engaging YouTuber-style delivery, confident and lively tone, light youthful masculine voice, quick dynamic pacing, sharp articulation, expressive and authentic, high energy but controlled, conversational flow, natural rhythm variation, spontaneous and human-like, slightly playful confidence, modern internet creator vibe, magnetic personality, realistic imperfections, fluid transitions, strong presence, excellent audio quality, no breath sounds, no inhalations, no mouth noises, no clicks, no lip smacks, no robotic cadence, no monotone, no overacting.",
    "Native English, neutral American accent. Male, young adult in his early 20s, youthful-sounding. Excellent audio quality. Persona: energetic YouTube creator. Emotion: charismatic, hyped, confident. Bright youthful timbre with clean, sharp articulation; speaks quickly with a brisk, punchy cadence and natural rhythm variation, like an excited creator talking to his audience. Conversational, spontaneous and human-like, slightly playful confidence, fluid transitions, strong presence. No breath sounds, no inhalations, no mouth noises, no clicks, no lip smacks, no robotic cadence, no monotone, no overacting.",
    "Very young-sounding adult male voice, early 20s, bursting with charisma and energy, speaking at a quick lively pace, neutral American accent, crisp clean pronunciation, engaging YouTuber-style delivery, confident and upbeat tone, light youthful timbre, rapid but controlled pacing, sharp articulation, expressive and authentic, conversational flow with natural rhythm shifts, spontaneous and human-like, playful self-assured attitude, modern content creator vibe, magnetic on-mic presence, subtle realistic imperfections, smooth fluid transitions, studio-quality clean audio, no breath sounds, no inhalations, no mouth noises, no clicks, no lip smacks, no robotic cadence, no monotone, no overacting.",
    "Native English with a neutral American accent. Young adult male, early 20s, fresh youthful sound. Studio quality. Persona: charismatic internet creator. Emotion: energetic, playful, confident. Clear youthful mid-to-high timbre; delivery is fast and punchy with a hurried yet controlled cadence, sharp articulation and expressive natural intonation, like a hyped YouTuber mid-video. Conversational and spontaneous with fluid transitions, realistic imperfections and strong presence. No breath sounds, no inhalations, no mouth noises, no clicks, no lip smacks, no robotic cadence, no monotone, no overacting.",
    "Young adult male voice, early 20s with a bright youthful ring, magnetic and high-energy, quick natural speech that never drags, neutral accent, clean precise pronunciation, engaging YouTuber-style delivery, lively confident tone, light masculine timbre, fast dynamic pacing with punchy emphasis, sharp articulation, expressive and genuine, high energy kept under control, conversational flow, varied natural rhythm, spontaneous and human-like, cheeky playful confidence, modern internet creator vibe, strong on-mic presence, realistic imperfections, fluid transitions, excellent audio quality, no breath sounds, no inhalations, no mouth noises, no clicks, no lip smacks, no robotic cadence, no monotone, no overacting.",
    "Energetic young adult male voice, early 20s and youthful-sounding, charismatic gaming-and-trends creator, speaking quickly in a rapid-fire yet clearly articulated way, neutral American accent, clean pronunciation, engaging YouTuber-style delivery, confident lively tone, bright youthful timbre, dynamic accelerated pacing, sharp articulation, expressive and authentic, controlled high energy, conversational flow, natural rhythm variation, spontaneous human-like feel, slightly playful confidence, modern internet creator vibe, magnetic personality, realistic imperfections, fluid transitions, strong presence, perfect audio quality, no breath sounds, no inhalations, no mouth noises, no clicks, no lip smacks, no robotic cadence, no monotone, no overacting.",
    "Native English, neutral American accent. Male, young adult, early 20s, youthful energy. Broadcast quality. Persona: upbeat YouTube storyteller. Emotion: excited, confident, playful. Light, clear youthful timbre with crisp articulation; talks fast with a brisk energetic tempo, punchy emphasis and lively natural intonation that rises and falls like real speech. Feels spontaneous, conversational and human-like, with fluid transitions, realistic imperfections and magnetic presence. No breath sounds, no inhalations, no mouth noises, no clicks, no lip smacks, no robotic cadence, no monotone, no overacting.",
    "Young adult male voice with a fresh youthful sound, radiating charisma and energy, fast conversational speech slightly quicker than a normal chat, neutral accent, clean pronunciation, engaging YouTuber-style delivery, confident and vivid tone, light youthful masculine voice, swift dynamic pacing, sharp articulation, expressive and authentic, high but controlled energy, natural flow with lively rhythm changes, spontaneous and human-like, playful self-assurance, modern internet creator vibe, magnetic personality, realistic imperfections, fluid transitions, strong presence, excellent clean audio, no breath sounds, no inhalations, no mouth noises, no clicks, no lip smacks, no robotic cadence, no monotone, no overacting.",
    "Charismatic young adult male voice, early 20s and very youthful-sounding, high-octane but never chaotic, quick punchy natural speech, neutral American accent, clean crisp pronunciation, engaging YouTuber-style delivery, confident lively tone, bright youthful timbre, fast pacing with sharp momentum, precise articulation, expressive and real, controlled excitement, conversational flow, natural rhythm variation, spontaneous human-like energy, slightly cocky playful charm, modern internet creator vibe, magnetic on-mic presence, realistic imperfections, fluid transitions, studio quality audio, no breath sounds, no inhalations, no mouth noises, no clicks, no lip smacks, no robotic cadence, no monotone, no overacting.",
    "Native English, neutral American accent. Young adult male, early 20s, youthful-sounding. Excellent quality. Persona: viral shorts narrator. Emotion: hyped, charismatic, genuine. Youthful clear timbre with sharp clean articulation; speaks at a fast clip with a quick, driving cadence, punchy stresses and natural conversational intonation, like a creator racing to share big news while staying perfectly clear. Spontaneous and human-like, slightly playful confidence, fluid transitions, strong presence. No breath sounds, no inhalations, no mouth noises, no clicks, no lip smacks, no robotic cadence, no monotone, no overacting.",
    "Lively young adult male voice with a youthful ring, natural-born entertainer, brisk fast-flowing speech, neutral accent, clean pronunciation, engaging YouTuber-style delivery, confident energetic tone, light youthful masculine timbre, quick agile pacing, razor-sharp articulation, expressive and authentic, big energy under tight control, conversational flow, organic rhythm variation, spontaneous and human-like, light playful confidence, modern internet creator vibe, magnetic personality, realistic imperfections, fluid transitions, commanding presence, perfect audio quality, no breath sounds, no inhalations, no mouth noises, no clicks, no lip smacks, no robotic cadence, no monotone, no overacting.",
    "Native English, neutral American accent. Male, young adult, early 20s, fresh youthful sound. Studio quality. Persona: charismatic trends commentator. Emotion: energetic, confident, slightly playful. Bright youthful timbre with clean sharp articulation; speaks noticeably fast with a lively, driving cadence, punchy natural emphasis and expressive intonation, like a young creator hyping up his audience without losing clarity. Conversational, spontaneous and human-like, realistic imperfections, fluid transitions, magnetic presence. No breath sounds, no inhalations, no mouth noises, no clicks, no lip smacks, no robotic cadence, no monotone, no overacting.",
]

OUT_DIR = "voice_prompts"


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    ok = True
    for i, prompt in enumerate(PROMPTS, 1):
        n = len(prompt)
        issues = []
        # ElevenLabs Voice Design accepts 20-1000 characters.
        if not 20 <= n <= 1000:
            issues.append("OUT OF LIMIT")
        banned = BANNED_RE.search(prompt)
        if banned:
            issues.append(f"BANNED WORD: {banned.group(0)}")
        if issues:
            ok = False
        print(f"voice_prompt_{i:02d}.txt: {n} chars {' '.join(issues) or 'OK'}")
        with open(os.path.join(OUT_DIR, f"voice_prompt_{i:02d}.txt"), "w", encoding="utf-8") as f:
            f.write(prompt + "\n")
    print(f"Wrote {len(PROMPTS)} prompts, unique: {len(set(PROMPTS))}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
