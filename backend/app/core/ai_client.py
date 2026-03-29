import asyncio
import logging
import os

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


async def call_ai(prompt: str, system: str) -> str:
    """
    Call AI providers in order: Groq → Gemini → OpenRouter.
    Returns the assistant's reply, or '{}' if all providers fail.
    """

    providers = [
        {
            "name": "Groq",
            "base_url": "https://api.groq.com/openai/v1",
            "api_key": os.getenv("GROQ_API_KEY", ""),
            "model": "llama-3.3-70b-versatile",
        },
        {
            "name": "Gemini",
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
            "api_key": os.getenv("GEMINI_API_KEY", ""),
            "model": "gemini-2.5-flash",
        },
        {
            "name": "OpenRouter",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": os.getenv("OPENROUTER_API_KEY", ""),
            "model": "meta-llama/llama-3.3-70b-instruct:free",
        },
    ]

    for provider in providers:
        name = provider["name"]
        if not provider["api_key"]:
            logger.warning("[AI] Skipping %s — API key not set", name)
            continue

        try:
            logger.info("[AI] Trying provider: %s", name)
            client = AsyncOpenAI(
                base_url=provider["base_url"],
                api_key=provider["api_key"],
            )

            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=provider["model"],
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                ),
                timeout=8.0,
            )

            result = response.choices[0].message.content or ""
            logger.info("[AI] Success via %s", name)
            return result

        except asyncio.TimeoutError:
            logger.warning("[AI] %s timed out after 8 s — trying next", name)
        except Exception as exc:
            logger.warning("[AI] %s failed: %s — trying next", name, exc)

    logger.error("[AI] All providers failed — returning empty fallback")
    return "{}"
