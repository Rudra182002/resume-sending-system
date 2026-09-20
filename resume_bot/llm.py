"""Provider-agnostic LLM calls. Nothing hardcoded - everything from .env.

  LLM_PROVIDER    anthropic | openai | azure   (auto-detected if unset)
  LLM_MODEL       model id, or Azure deployment name
  ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL
  OPENAI_API_KEY  / OPENAI_BASE_URL
  AZURE_OPENAI_API_KEY / AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_API_VERSION
"""
import os, json, re


def _strip_fence(t):
    return re.sub(r"^```(?:json)?|```$", "", t.strip(), flags=re.M).strip()


def provider():
    p = (os.getenv("LLM_PROVIDER") or "").lower().strip()
    if p:
        return p
    if os.getenv("AZURE_OPENAI_API_KEY") and os.getenv("AZURE_OPENAI_ENDPOINT"):
        return "azure"
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    return "none"


def configured():
    return provider() != "none"


def model_name():
    return os.getenv("LLM_MODEL") or {
        "anthropic": "claude-sonnet-5",
        "openai": "gpt-4.1-mini",
        "azure": "",
    }.get(provider(), "")


def _client_and_call(system, user, max_tokens, as_json):
    p = provider()

    if p == "anthropic":
        from anthropic import Anthropic
        kw = {}
        if os.getenv("ANTHROPIC_BASE_URL") or os.getenv("ANTHROPIC_API_BASE"):
            kw["base_url"] = (os.getenv("ANTHROPIC_BASE_URL")
                              or os.getenv("ANTHROPIC_API_BASE"))
        r = Anthropic(**kw).messages.create(
            model=model_name(), max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user}])
        # With extended thinking on, content[0] is a ThinkingBlock, not the
        # answer. Collect the text blocks rather than assuming an index.
        parts = [b.text for b in r.content
                 if getattr(b, "type", None) == "text" and hasattr(b, "text")]
        if not parts:                      # older/plain shapes
            parts = [b.text for b in r.content if hasattr(b, "text")]
        if not parts:
            raise RuntimeError(
                "no text block in response; blocks="
                + ",".join(getattr(b, "type", "?") for b in r.content))
        return "\n".join(parts)

    if p == "azure":
        from openai import AzureOpenAI
        client = AzureOpenAI(
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2025-04-01-preview"))
    else:
        from openai import OpenAI
        client = OpenAI(base_url=os.getenv("OPENAI_BASE_URL") or None)

    kw = {"response_format": {"type": "json_object"}} if as_json else {}
    try:
        r = client.chat.completions.create(
            model=model_name(), max_completion_tokens=max_tokens,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}], **kw)
    except TypeError:
        # older deployments reject max_completion_tokens
        r = client.chat.completions.create(
            model=model_name(), max_tokens=max_tokens,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}], **kw)
    return r.choices[0].message.content


def complete(system, user, max_tokens=2000, as_json=True):
    if provider() == "none":
        raise RuntimeError("no LLM configured - set a key in .env, then: "
                           "python -m resume_bot doctor")
    text = _client_and_call(system, user, max_tokens, as_json)
    return json.loads(_strip_fence(text)) if as_json else text
