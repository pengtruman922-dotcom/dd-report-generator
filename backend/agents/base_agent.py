"""Base AI client wrapper using OpenAI-compatible API."""

from __future__ import annotations

from typing import Any

from openai import AsyncOpenAI


def create_client(base_url: str, api_key: str) -> AsyncOpenAI:
    """Create an AsyncOpenAI client for the given endpoint."""
    return AsyncOpenAI(base_url=base_url, api_key=api_key)


async def chat_completion(
    client: AsyncOpenAI,
    model: str,
    messages: list[dict],
    tools: list[dict] | None = None,
    temperature: float = 0.3,
) -> tuple[Any, dict]:
    """Call chat completions and return (response, usage_dict).

    Returns:
        tuple: (response, usage_dict) where usage_dict contains:
            - prompt_tokens: int
            - completion_tokens: int
            - total_tokens: int
    """
    kwargs: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    response = await client.chat.completions.create(**kwargs)

    # Extract usage information
    usage_dict = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    if response.usage:
        usage_dict["prompt_tokens"] = response.usage.prompt_tokens or 0
        usage_dict["completion_tokens"] = response.usage.completion_tokens or 0
        usage_dict["total_tokens"] = response.usage.total_tokens or 0

    return response, usage_dict


async def chat_completion_stream(
    client: AsyncOpenAI,
    model: str,
    messages: list[dict],
    temperature: float = 0.3,
):
    """Call chat completions with streaming and yield chunks.

    Yields:
        str: Content chunks from the streaming response

    Note: Streaming responses don't include usage information until the end.
    The final chunk may contain usage data, but it's not guaranteed.
    """
    response = await client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        stream=True,
    )

    async for chunk in response:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content
