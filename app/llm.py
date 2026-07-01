import os
import re
from groq import Groq, GroqError

ALLOWED_MODELS = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.6-27b"]
_DEFAULT_MODEL = "openai/gpt-oss-120b"
_FAST_MODEL = "openai/gpt-oss-20b"

_SYSTEM_PROMPT = (
    "Sen yardımcı bir asistansın. "
    "Her zaman düzgün ve akıcı Türkçe yanıt ver. "
    "Yanıtlarına başka dillerden kelime veya karakter karıştırma."
)


class LLMError(Exception):
    pass


def _strip_thinking(text: str) -> str:
    # Remove complete <think>...</think> blocks (multi-line)
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    # Lone </think> → model started a block but response was cut; drop everything before it
    if '</think>' in text:
        text = text.split('</think>', 1)[1]
    # Lone <think> → model started reasoning but never closed it; drop from there onward
    if '<think>' in text:
        text = text.split('<think>', 1)[0]
    return text.strip()


def _client() -> Groq:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise LLMError("GROQ_API_KEY environment variable is not set")
    return Groq(api_key=api_key)


def generate_reply(history: list[dict], model: str | None = None) -> dict:
    _model = model if model in ALLOWED_MODELS else _DEFAULT_MODEL
    messages = [{"role": "system", "content": _SYSTEM_PROMPT}, *history]
    try:
        response = _client().chat.completions.create(
            model=_model,
            messages=messages,
        )
    except GroqError as exc:
        raise LLMError(str(exc)) from exc

    usage = response.usage
    return {
        "content": _strip_thinking(response.choices[0].message.content),
        "model": response.model,
        "metadata": {
            "provider": "groq",
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
        },
    }


_TITLE_SYSTEM_PROMPT = (
    "Sen kısa sohbet başlıkları üreten bir asistansın. "
    "Sana verilen mesaj için 3-5 kelimelik, tek satırlık kısa bir başlık döndür. "
    "SADECE başlığı yaz: açıklama yapma, düşünme/akıl yürütme gösterme, "
    "tırnak işareti veya noktalama ekleme."
)


def _fallback_title(first_message: str) -> str:
    words = first_message.split()
    title = " ".join(words[:6]) + ("..." if len(words) > 6 else "")
    return title.strip() or "Yeni sohbet"


def _clean_title(text: str) -> str:
    text = _strip_thinking(text)
    # Collapse newlines/extra whitespace to a single line
    text = " ".join(text.split())
    # Strip wrapping quotes the model sometimes adds
    text = text.strip().strip('"').strip("'").strip()
    return text


def generate_title(first_message: str) -> str:
    try:
        response = _client().chat.completions.create(
            model=_FAST_MODEL,
            messages=[
                {"role": "system", "content": _TITLE_SYSTEM_PROMPT},
                {"role": "user", "content": first_message},
            ],
            max_tokens=64,
        )
        raw = response.choices[0].message.content or ""
        title = _clean_title(raw)
        used = title if title else _fallback_title(first_message)
        print(
            "[generate_title] raw=%r | cleaned=%r | used=%r"
            % (raw, title, used)
        )
        return used
    except Exception as exc:  # noqa: BLE001 — title must never break the request
        used = _fallback_title(first_message)
        print("[generate_title] error=%r | fallback used=%r" % (exc, used))
        return used
