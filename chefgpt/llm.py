import json
import os
import re
import time
from google import genai
from google.genai import errors, types

MODEL = os.getenv("CHEFGPT_MODEL", "gemini-3.1-flash-lite")
_client = None


def call_json(system: str, messages: list[dict], max_tokens: int = 1500) -> dict:
    global _client
    if _client is None:
        _client = genai.Client(
            api_key=os.environ["GEMINI_API_KEY"],
            http_options=types.HttpOptions(timeout=60000),
        )
    contents = [
        types.Content(role="model" if m["role"] == "assistant" else "user",
                      parts=[types.Part(text=m["content"])])
        for m in messages
    ]
    config = types.GenerateContentConfig(
        system_instruction=system,
        response_mime_type="application/json",
        max_output_tokens=max_tokens * 4,
    )

    resp = None
    for attempt in range(3):
        try:
            resp = _client.models.generate_content(
                model=MODEL, contents=contents, config=config
            )
            break
        except errors.ServerError as e:  # 503 busy: worth retrying
            print(f"Google is busy ({e.code}), retry {attempt + 1}/3 in 10s...")
            time.sleep(10)
        except errors.ClientError as e:  # 429, 404, bad key: retrying won't help
            raise RuntimeError(f"Google refused the request ({e.code}): {e.message}")

    if resp is None:
        raise RuntimeError("Google is still busy. Try again in a few minutes.")

    text = (resp.text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    return json.loads(text)