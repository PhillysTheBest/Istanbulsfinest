import os
import base64
import json
from google import genai
from google.genai import types

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "")

_gemini_client = genai.Client(api_key=GEMINI_API_KEY)
MODEL_ID = "gemini-2.5-flash"


def _flatten_skills(skills_dict: dict) -> str:
    """Convert nested skills tree to a readable bullet-point summary."""
    lines = []
    if not isinstance(skills_dict, dict):
        return str(skills_dict)
    for domain, languages in skills_dict.items():
        if not isinstance(languages, dict):
            continue
        for language, categories in languages.items():
            if not isinstance(categories, dict):
                continue
            for category, skill_list in categories.items():
                if isinstance(skill_list, list) and skill_list:
                    lines.append(f"  - {', '.join(str(s) for s in skill_list)} ({domain} / {language} / {category})")
    return "\n".join(lines) if lines else "No specific skills listed."


def generate_interview_script(
    job_title: str,
    job_preview: str,
    job_qualifications: str,
    applicant_name: str,
    skills_dict: dict,
) -> str:
    """Call Gemini to generate a natural self-presentation script for an interview."""
    skills_summary = _flatten_skills(skills_dict)

    prompt = f"""You are a career coach helping a job applicant craft a natural, compelling self-introduction for a job interview.

JOB DETAILS:
Title: {job_title}
Description: {job_preview}
Requirements / Qualifications: {job_qualifications}

APPLICANT:
Name: {applicant_name}
Skills:
{skills_summary}

TASK:
Write a spoken self-presentation script for {applicant_name} that:
1. Lasts roughly 45–75 seconds when read aloud at a natural pace (about 120–180 words).
2. Opens with a warm, confident greeting ("Hi, I'm …" or similar).
3. Highlights the 2–4 most relevant skills or experiences that match the job requirements, weaving them naturally into the flow.
4. Reflects the tone and mindset the employer is looking for (e.g. entrepreneurial, collaborative, detail-oriented) based on the job description.
5. Sounds genuinely human — varied sentence length, natural rhythm, not a list of bullet points read aloud. Avoid clichés like "I am passionate about…" or "I am a team player."
6. Ends with a confident, forward-looking statement showing enthusiasm for the role.

Return ONLY the spoken script text, ready to be read aloud. No headings, no notes, no markdown formatting.
"""

    config = types.GenerateContentConfig(temperature=0.75)
    response = _gemini_client.models.generate_content(
        model=MODEL_ID,
        contents=prompt,
        config=config,
    )
    return response.text.strip()


def generate_audio_base64(script: str) -> str:
    """Call ElevenLabs TTS and return the audio as a base64-encoded string."""
    if not ELEVENLABS_API_KEY:
        raise RuntimeError(
            "ELEVENLABS_API_KEY is not set. "
            "Please add it to your .env file."
        )

    import requests as req

    voice_id = ELEVENLABS_VOICE_ID or "EXAVITQu4vr4xnSDxMaL"

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    payload = {
        "text": script[:3000],
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.45,
            "similarity_boost": 0.75,
            "style": 0.35,
            "use_speaker_boost": True,
        },
    }

    response = req.post(url, headers=headers, json=payload, timeout=90)
    if response.status_code != 200:
        try:
            detail = response.json().get("detail", {})
            if isinstance(detail, dict):
                msg = detail.get("message", response.text[:200])
            else:
                msg = str(detail)
        except Exception:
            msg = response.text[:200]
        raise RuntimeError(f"ElevenLabs API error {response.status_code}: {msg}")

    return base64.b64encode(response.content).decode("utf-8")
