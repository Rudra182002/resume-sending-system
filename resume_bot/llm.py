"""Provider-agnostic LLM call.

Set LLM_PROVIDER to anthropic | openai | compatible.
  anthropic   -> ANTHROPIC_API_KEY
  openai      -> OPENAI_API_KEY
  compatible  -> OPENAI_API_KEY + OPENAI_BASE_URL   (any OpenAI-shaped endpoint:
                 Together, Groq, OpenRouter, DeepSeek, a local Ollama, ...)

Use a key that belongs to you. A work-issued key is provisioned for that
employer's work, which this is not.
"""
import os, json, re


def _strip_fence(t):
    return re.sub(r"^```(?:json)?|```$", "", t.strip(), flags=re.M).strip()


def provider():
    p = os.getenv("LLM_PROVIDER", "").lower().strip()
    if p:
        return p
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.getenv("OPENAI_API_KEY"):
        return "openai" if not os.getenv("OPENAI_BASE_URL") else "compatible"
    return "none"


def configured():
    return provider() != "none"


def model_name():
    if os.getenv("LLM_MODEL"):
        return os.getenv("LLM_MODEL")
    return {"anthropic": "claude-sonnet-5",
            "openai": "gpt-4.1-mini",
            "compatible": "llama-3.1-8b-instruct"}.get(provider(), "")


def complete(system, user, max_tokens=2000, as_json=True):
    """One completion. Returns parsed dict when as_json, else raw text."""
    p = provider()
    if p == "none":
        raise RuntimeError("no LLM configured - set ANTHROPIC_API_KEY or OPENAI_API_KEY")

    if p == "anthropic":
        from anthropic import Anthropic
        r = Anthropic().messages.create(
            model=model_name(), max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user}])
        text = r.content[0].text
    else:
        from openai import OpenAI
        client = OpenAI(base_url=os.getenv("OPENAI_BASE_URL") or None)
        kwargs = {}
        if as_json and p == "openai":
            kwargs["response_format"] = {"type": "json_object"}
        r = client.chat.completions.create(
            model=model_name(), max_completion_tokens=max_tokens,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}], **kwargs)
        text = r.choices[0].message.content

    return json.loads(_strip_fence(text)) if as_json else text
