import os
from groq import Groq, GroqError

_DEFAULT_MODEL = "llama-3.3-70b-versatile"


class LLMError(Exception):
    pass


def _client() -> Groq:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise LLMError("GROQ_API_KEY environment variable is not set")
    return Groq(api_key=api_key)


def generate_reply(history: list[dict], model: str | None = None) -> dict:
    _model = model or _DEFAULT_MODEL
    try:
        response = _client().chat.completions.create(
            model=_model,
            messages=history,
        )
    except GroqError as exc:
        raise LLMError(str(exc)) from exc

    choice = response.choices[0]
    usage = response.usage
    return {
        "content": choice.message.content,
        "model": response.model,
        "metadata": {
            "provider": "groq",
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
        },
    }


def generate_title(first_message: str) -> str:
    prompt = (
        f"Aşağıdaki mesajdan 3-5 kelimelik kısa bir sohbet başlığı üret. "
        f"Sadece başlığı yaz, başka hiçbir şey ekleme.\n\nMesaj: {first_message}"
    )
    try:
        response = _client().chat.completions.create(
            model=_DEFAULT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=20,
        )
        return response.choices[0].message.content.strip()
    except (GroqError, LLMError):
        words = first_message.split()
        return " ".join(words[:6]) + ("..." if len(words) > 6 else "")
