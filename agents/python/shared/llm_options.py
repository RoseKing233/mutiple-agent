"""Model-compatible sampling options shared by native agents and SDK writers."""

from __future__ import annotations

from shared.config import settings


def sampling_options(temperature: float, *, model: str | None = None) -> dict[str, float]:
    """Omit custom sampling for reasoning models without changing their reasoning effort.

    GPT-5 (including gpt-5.6-luna) and o-series default reasoning requests reject
    temperature. Omitting it also works for models that support it at effort=none.
    Other models retain the configured value. No provider-error retries are added.
    """
    candidates = [model] if model is not None else [settings.LLM_MODEL]
    if settings.LLM_PROVIDER.lower() == "azure":
        # A deployment may be an arbitrary alias. Respect the underlying model
        # setting as well for both native and direct SDK calls.
        candidates.extend([settings.LLM_MODEL, settings.AZURE_OPENAI_DEPLOYMENT])
    for candidate in candidates:
        name = candidate.strip().lower().rsplit("/", 1)[-1]
        if name == "gpt-5" or name.startswith(("gpt-5-", "gpt-5.")):
            return {}
        if any(name == family or name.startswith(f"{family}-") for family in ("o1", "o3", "o4")):
            return {}
    return {"temperature": temperature}
