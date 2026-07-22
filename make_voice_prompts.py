#!/usr/bin/env python3
"""Generate 11 ElevenLabs Voice Design prompts as .txt files.

Based on the user's reference prompt (young male 16-18, energetic
YouTuber style), with slightly faster pacing. Prompts follow ElevenLabs
Voice Design guidance: explicit pacing, audio-quality descriptor,
20-1000 chars, some in the recommended structured format.
"""
import os
import sys

PROMPTS = [
    "Young male voice, 16-18 years old, charismatic and energetic, very fast-paced natural speech, neutral American accent, clean pronunciation, engaging YouTuber-style delivery, confident and lively tone, youthful masculine voice, quick dynamic pacing, sharp articulation, expressive and authentic, high energy but controlled, conversational flow, natural rhythm variation, spontaneous and human-like, slightly playful confidence, modern internet creator vibe, magnetic personality, realistic imperfections, fluid transitions, strong presence, excellent audio quality, no breath sounds, no inhalations, no mouth noises, no clicks, no lip smacks, no robotic cadence, no monotone, no overacting.",
    "Native English, neutral American accent. Male, 16-18, adolescent. Excellent audio quality. Persona: energetic YouTube creator. Emotion: charismatic, hyped, confident. Bright youthful timbre with clean, sharp articulation; speaks quickly with a brisk, punchy cadence and natural rhythm variation, like an excited creator talking to his audience. Conversational, spontaneous and human-like, slightly playful confidence, fluid transitions, strong presence. No breath sounds, no inhalations, no mouth noises, no clicks, no lip smacks, no robotic cadence, no monotone, no overacting.",
    "Teenage male voice, around 17, bursting with charisma and energy, speaking at a quick lively pace, neutral American accent, crisp clean pronunciation, engaging YouTuber-style delivery, confident and upbeat tone, light youthful timbre, rapid but controlled pacing, sharp articulation, expressive and authentic, conversational flow with natural rhythm shifts, spontaneous and human-like, playful self-assured attitude, modern content creator vibe, magnetic on-mic presence, subtle realistic imperfections, smooth fluid transitions, studio-quality clean audio, no breath sounds, no inhalations, no mouth noises, no clicks, no lip smacks, no robotic cadence, no monotone, no overacting.",
    "Native English with a neutral American accent. Young male, late teens, 16-18. Studio quality. Persona: charismatic internet creator. Emotion: energetic, playful, confident. Clear youthful mid-to-high timbre; delivery is fast and punchy with a hurried yet controlled cadence, sharp articulation and expressive natural intonation, like a hyped YouTuber mid-video. Conversational and spontaneous with fluid transitions, realistic imperfections and strong presence. No breath sounds, no inhalations, no mouth noises, no clicks, no lip smacks, no robotic cadence, no monotone, no overacting.",
    "Young male voice, 16-18 years old, magnetic and high-energy, quick natural speech that never drags, neutral accent, clean precise pronunciation, engaging YouTuber-style delivery, lively confident tone, youthful masculine timbre, fast dynamic pacing with punchy emphasis, sharp articulation, expressive and genuine, high energy kept under control, conversational flow, varied natural rhythm, spontaneous and human-like, cheeky playful confidence, modern internet creator vibe, strong on-mic presence, realistic imperfections, fluid transitions, excellent audio quality, no breath sounds, no inhalations, no mouth noises, no clicks, no lip smacks, no robotic cadence, no monotone, no overacting.",
    "Energetic teenage male voice, 16-18, charismatic gaming-and-trends creator, speaking quickly in a rapid-fire yet clearly articulated way, neutral American accent, clean pronunciation, engaging YouTuber-style delivery, confident lively tone, bright youthful timbre, dynamic accelerated pacing, sharp articulation, expressive and authentic, controlled high energy, conversational flow, natural rhythm variation, spontaneous human-like feel, slightly playful confidence, modern internet creator vibe, magnetic personality, realistic imperfections, fluid transitions, strong presence, perfect audio quality, no breath sounds, no inhalations, no mouth noises, no clicks, no lip smacks, no robotic cadence, no monotone, no overacting.",
    "Native English, neutral American accent. Male, adolescent, 16-18. Broadcast quality. Persona: upbeat YouTube storyteller. Emotion: excited, confident, playful. Light, clear teenage timbre with crisp articulation; talks fast with a brisk energetic tempo, punchy emphasis and lively natural intonation that rises and falls like real speech. Feels spontaneous, conversational and human-like, with fluid transitions, realistic imperfections and magnetic presence. No breath sounds, no inhalations, no mouth noises, no clicks, no lip smacks, no robotic cadence, no monotone, no overacting.",
    "Young male voice in his late teens, radiating charisma and energy, fast conversational speech slightly quicker than a normal chat, neutral accent, clean pronunciation, engaging YouTuber-style delivery, confident and vivid tone, youthful masculine voice, swift dynamic pacing, sharp articulation, expressive and authentic, high but controlled energy, natural flow with lively rhythm changes, spontaneous and human-like, playful self-assurance, modern internet creator vibe, magnetic personality, realistic imperfections, fluid transitions, strong presence, excellent clean audio, no breath sounds, no inhalations, no mouth noises, no clicks, no lip smacks, no robotic cadence, no monotone, no overacting.",
    "Charismatic teenage male voice, 16-18 years old, high-octane but never chaotic, quick punchy natural speech, neutral American accent, clean crisp pronunciation, engaging YouTuber-style delivery, confident lively tone, youthful bright timbre, fast pacing with sharp momentum, precise articulation, expressive and real, controlled excitement, conversational flow, natural rhythm variation, spontaneous human-like energy, slightly cocky playful charm, modern internet creator vibe, magnetic on-mic presence, realistic imperfections, fluid transitions, studio quality audio, no breath sounds, no inhalations, no mouth noises, no clicks, no lip smacks, no robotic cadence, no monotone, no overacting.",
    "Native English, neutral American accent. Young male, 16-18. Excellent quality. Persona: viral shorts narrator. Emotion: hyped, charismatic, genuine. Youthful clear timbre with sharp clean articulation; speaks at a fast clip with a quick, driving cadence, punchy stresses and natural conversational intonation, like a creator racing to share big news while staying perfectly clear. Spontaneous and human-like, slightly playful confidence, fluid transitions, strong presence. No breath sounds, no inhalations, no mouth noises, no clicks, no lip smacks, no robotic cadence, no monotone, no overacting.",
    "Lively young male voice, 16-18, natural-born entertainer, brisk fast-flowing speech, neutral accent, clean pronunciation, engaging YouTuber-style delivery, confident energetic tone, youthful masculine timbre, quick agile pacing, razor-sharp articulation, expressive and authentic, big energy under tight control, conversational flow, organic rhythm variation, spontaneous and human-like, light playful confidence, modern internet creator vibe, magnetic personality, realistic imperfections, fluid transitions, commanding presence, perfect audio quality, no breath sounds, no inhalations, no mouth noises, no clicks, no lip smacks, no robotic cadence, no monotone, no overacting.",
]

OUT_DIR = "voice_prompts"


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    ok = True
    for i, prompt in enumerate(PROMPTS, 1):
        n = len(prompt)
        # ElevenLabs Voice Design accepts 20-1000 characters.
        status = "OK" if 20 <= n <= 1000 else "OUT OF LIMIT"
        if status != "OK":
            ok = False
        print(f"voice_prompt_{i:02d}.txt: {n} chars {status}")
        with open(os.path.join(OUT_DIR, f"voice_prompt_{i:02d}.txt"), "w", encoding="utf-8") as f:
            f.write(prompt + "\n")
    print(f"Wrote {len(PROMPTS)} prompts, unique: {len(set(PROMPTS))}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
