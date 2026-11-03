
import json
import os
import re
import time

from google import genai
from google.genai import errors, types


MODEL = os.getenv("CHEFGPT_MODEL", "gemini-3.1-flash-lite")

_client = None


def get_client():
    """Create the Gemini client only when needed."""
    global _client

    if _client is None:
        api_key = os.getenv("GEMINI_API_KEY")

        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is missing. "
                "Add it to your Render environment variables."
            )

        _client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=60000
            ),
        )

    return _client


def call_json(
    system: str,
    messages: list[dict],
    max_tokens: int = 1500,
) -> dict:
    """
    Send a request to Gemini and return a JSON dictionary.
    """

    client = get_client()

    contents = []

    for message in messages:
        role = (
            "model"
            if message["role"] == "assistant"
            else "user"
        )

        contents.append(
            types.Content(
                role=role,
                parts=[
                    types.Part.from_text(
                        text=message["content"]
                    )
                ],
            )
        )

    config = types.GenerateContentConfig(
        system_instruction=system,
        response_mime_type="application/json",
        max_output_tokens=max_tokens,
    )

    response = None

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=MODEL,
                contents=contents,
                config=config,
            )

            break

        except errors.ServerError as e:
            if attempt == 2:
                raise RuntimeError(
                    "Gemini server is unavailable. "
                    "Please try again later."
                ) from e

            wait_time = 2 ** (attempt + 1)

            print(
                f"Gemini server error: {e}. "
                f"Retrying in {wait_time} seconds..."
            )

            time.sleep(wait_time)

        except errors.ClientError as e:
            raise RuntimeError(
                f"Gemini API request failed: "
                f"{e.code} - {e.message}"
            ) from e

    if response is None:
        raise RuntimeError(
            "Gemini did not return a response."
        )

    response_text = (response.text or "").strip()

    if not response_text:
        raise RuntimeError(
            "Gemini returned an empty response."
        )

    # Remove Markdown JSON code fences if present.
    response_text = re.sub(
        r"^```(?:json)?\s*|\s*```$",
        "",
        response_text,
        flags=re.IGNORECASE,
    ).strip()

    try:
        result = json.loads(response_text)

    except json.JSONDecodeError as e:
        print(
            "Invalid JSON returned by Gemini:",
            response_text[:500],
        )

        raise RuntimeError(
            "Gemini returned invalid JSON."
        ) from e

    if not isinstance(result, dict):
        raise RuntimeError(
            "Gemini response must be a JSON object."
        )

    return result
