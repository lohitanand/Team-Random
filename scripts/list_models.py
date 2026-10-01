"""Print the models available for the configured LLM provider.

Usage (PowerShell, from the repo root):
    python -m scripts.list_models
    python -m scripts.list_models --provider openrouter --filter free
"""
from __future__ import annotations

import argparse

import httpx

from backend.app.config import ProviderConfig, get_settings


def fetch_model_ids(provider: ProviderConfig, timeout: float) -> list[str]:
    response = httpx.get(
        f"{provider.base_url}/models",
        headers={"Authorization": f"Bearer {provider.api_key}"},
        timeout=timeout,
    )
    response.raise_for_status()
    return sorted(item["id"] for item in response.json().get("data", []))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--provider", choices=["groq", "openrouter"], default=None)
    parser.add_argument("--filter", default="", help="only show IDs containing this text")
    args = parser.parse_args(argv)

    settings = get_settings()
    provider = settings.provider(args.provider or settings.llm_provider)
    if not provider.api_key:
        print(f"No API key for '{provider.name}'. Set {provider.api_key_env} in .env first.")
        return 1

    try:
        model_ids = fetch_model_ids(provider, settings.llm_timeout_seconds)
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        print(f"Could not list models from {provider.base_url}: {exc}")
        return 1

    configured = {provider.model_fast: "fast", provider.model_agent: "agent"}
    shown = [m for m in model_ids if args.filter.lower() in m.lower()]
    print(f"{provider.name}: {len(shown)} of {len(model_ids)} models")
    for model_id in shown:
        tag = f"   <- LLM {configured[model_id]} model" if model_id in configured else ""
        print(f"  {model_id}{tag}")

    for model_id, role in configured.items():
        if model_id and model_id not in model_ids:
            print(f"WARNING: configured {role} model '{model_id}' is not available on {provider.name}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
