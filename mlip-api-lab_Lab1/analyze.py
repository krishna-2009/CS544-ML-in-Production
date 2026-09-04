import json
import os
import re
from typing import Any, Dict

from litellm import completion

# groq/ is LiteLLM's provider prefix; openai/gpt-oss-120b is Groq's model ID.
# llama-3.3-70b-versatile was decommissioned by Groq on 2026-08-16.
MODEL = os.environ.get("GROQ_MODEL", "groq/openai/gpt-oss-120b")

# The contract this API guarantees to its callers.
SCHEMA = {
    "destination": str,
    "price_range": str,
    "ideal_visit_times": list,
    "top_attractions": list,
}


class ModelOutputError(Exception):
    """The model responded, but not with output matching our schema."""


def _extract_json(content: str) -> Any:
    """Parse model output into Python, tolerating code fences or a preamble."""
    content = content.strip()

    fenced = re.search(r"```(?:json)?\s*(.*?)```", content, re.DOTALL)
    if fenced:
        content = fenced.group(1).strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start, end = content.find("{"), content.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(content[start:end + 1])
            except json.JSONDecodeError:
                pass
        raise ModelOutputError(f"Model did not return valid JSON. Raw output: {content!r}")


def _validate(data: Any) -> Dict[str, Any]:
    """Enforce the schema. Returns only the contracted keys."""
    if not isinstance(data, dict):
        raise ModelOutputError(f"Expected a JSON object, got {type(data).__name__}.")

    missing = [k for k in SCHEMA if k not in data]
    if missing:
        raise ModelOutputError(f"Missing required fields: {missing}")

    for key, expected in SCHEMA.items():
        if not isinstance(data[key], expected):
            raise ModelOutputError(
                f"Field '{key}' should be {expected.__name__}, "
                f"got {type(data[key]).__name__}."
            )

    for key in ("ideal_visit_times", "top_attractions"):
        if not data[key]:
            raise ModelOutputError(f"Field '{key}' must not be empty.")
        if not all(isinstance(item, str) for item in data[key]):
            raise ModelOutputError(f"Field '{key}' must contain only strings.")

    # Drop anything the model invented beyond the contract.
    return {k: data[k] for k in SCHEMA}


def get_itinerary(destination: str) -> Dict[str, Any]:
    """
    Returns a schema-validated dict with keys:
      - destination
      - price_range
      - ideal_visit_times
      - top_attractions
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY environment variable is not set.")

    prompt = f"""
    Provide travel details for '{destination}'.
    Respond strictly in JSON format with these exact keys:
    - "destination": string
    - "price_range": string (e.g., "$$", "Budget-friendly", "$$$")
    - "ideal_visit_times": list of strings (e.g., ["Spring", "Autumn"])
    - "top_attractions": list of strings (top 3-5 places)
    """

    response = completion(
        model=MODEL,
        api_key=api_key,
        messages=[
            {
                "role": "system",
                "content": "You are a travel assistant that strictly outputs valid JSON.",
            },
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content
    return _validate(_extract_json(content))