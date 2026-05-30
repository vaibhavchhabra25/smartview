import json
import os
from dotenv import load_dotenv
from groq import Groq
from pydantic import BaseModel
from typing import Type, TypeVar

load_dotenv()

T = TypeVar("T", bound=BaseModel)

QUALITY_MODEL = "llama-3.3-70b-versatile"   # schema extraction + question generation
FAST_MODEL    = "llama-3.1-8b-instant"       # summary narrative (cheap, fast)

_client: Groq | None = None


def get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    return _client


def call_structured(
    prompt: str,
    schema: Type[T],
    model: str = QUALITY_MODEL,
    system: str = "You are a precise data extractor. Always call the output function with data matching the schema exactly.",
) -> T:
    """
    Calls Groq with forced function-calling so the response always matches
    the Pydantic schema. The model must fill the function's parameters schema —
    it cannot return free text.
    """
    tool = {
        "type": "function",
        "function": {
            "name": "output",
            "description": "Return structured output matching the schema exactly.",
            "parameters": schema.model_json_schema(),
        },
    }

    response = get_client().chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ],
        tools=[tool],
        tool_choice={"type": "function", "function": {"name": "output"}},
    )

    raw = json.loads(response.choices[0].message.tool_calls[0].function.arguments)
    return schema.model_validate(raw)
