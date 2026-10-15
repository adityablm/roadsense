"""
Asks Google Gemini to write the complaint letter.

Two design choices worth explaining in an interview:

1. Grounding: Gemini is given ONLY facts from our database (location, damage
   found, number of reports, dates) and told not to add anything else. This
   stops the AI from inventing details like fake reference numbers or names.

2. Fallbacks: free AI models are sometimes overloaded (error 503) or we hit the
   free limit (error 429). Instead of failing, we wait a moment and retry, then
   move on to the next model in a list. Other errors (like a wrong API key) are
   NOT retried, because retrying can't fix them.
"""
import json
import time

from . import config

LANGUAGES = {"en": "English", "te": "Telugu (తెలుగు)"}
RETRYABLE = {429, 500, 503, 504}   # busy / rate-limited / temporary server problems
TRIES_PER_MODEL = 2
_client = None


def _get_client():
    global _client
    if _client is None:
        if not config.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is empty. Put your key in backend/.env")
        from google import genai      # imported here so the app still starts if the key is missing
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


def models_to_try() -> list[str]:
    seen, order = set(), []
    for m in [config.GEMINI_MODEL, *config.GEMINI_FALLBACK_MODELS]:
        if m and m not in seen:
            seen.add(m)
            order.append(m)
    return order


def generate(prompt: str, temperature: float = 0.3, wait_seconds: float = 1.5) -> tuple[str, str]:
    """Returns (text, name of the model that answered)."""
    from google.genai import errors, types
    client = _get_client()
    problems = []
    for model in models_to_try():
        for attempt in range(TRIES_PER_MODEL):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(temperature=temperature),
                )
                text = (response.text or "").strip()
                if text:
                    return text, model
                problems.append(f"{model}: empty answer")
                break                                  # empty answer: try the next model
            except errors.APIError as exc:
                if exc.code not in RETRYABLE:
                    raise                              # e.g. bad key: retrying won't help
                problems.append(f"{model}: {exc.code} {exc.status}")
                if attempt + 1 < TRIES_PER_MODEL:
                    time.sleep(wait_seconds * (attempt + 1))
    raise RuntimeError("All Gemini models are busy right now. Try again in a minute. (" + "; ".join(problems) + ")")


def build_prompt(facts: dict, lang: str) -> str:
    language = LANGUAGES[lang]
    return f"""You are helping a citizen write a short, formal complaint letter about road damage.

Rules:
- Write the whole letter in {language}.
- Address it to: {config.CITY_AUTHORITY}.
- Use ONLY the facts in the JSON below. Do not invent names, phone numbers, reference numbers,
  laws, accident reports or anything else that is not in the facts.
- Mention the location (address if given, and the coordinates with the map link),
  the types and counts of damage, how many separate reports and people, and the dates.
- Politely request inspection and repair, and mention the safety risk to road users in general terms.
- End with placeholders for the sender: [Your Name], [Your Phone], [Date].
- Keep it under 250 words. Plain text only, no markdown.

Facts:
{json.dumps(facts, ensure_ascii=False, indent=2)}
"""


def draft_complaint(facts: dict, lang: str) -> str:
    if lang not in LANGUAGES:
        raise ValueError("lang must be 'en' or 'te'")
    text, _model = generate(build_prompt(facts, lang))
    return text
