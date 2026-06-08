#!/usr/bin/env python3
"""
Quick API key validation test.

Usage:
    ANTHROPIC_API_KEY=sk-ant-... python scripts/test_api_keys.py
    OPENAI_API_KEY=sk-... python scripts/test_api_keys.py
    GOOGLE_API_KEY=... python scripts/test_api_keys.py

Tests that each configured API key can successfully make a minimal API call.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
SKIP = "\033[90m-\033[0m"


async def test_openai():
    """Test OpenAI API key."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None, "Not configured"

    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=api_key, timeout=30)
        response = await client.chat.completions.create(
            model="gpt-4.1-nano",
            messages=[{"role": "user", "content": "Say 'OK'"}],
            max_tokens=5,
        )
        await client.close()
        return True, f"Model: gpt-4.1-nano, Response: {response.choices[0].message.content}"
    except Exception as e:
        return False, str(e)


async def test_anthropic():
    """Test Anthropic API key."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None, "Not configured"

    try:
        from anthropic import AsyncAnthropic
        kwargs = {"api_key": api_key, "timeout": 30}
        base_url = os.environ.get("ANTHROPIC_BASE_URL")
        if base_url:
            kwargs["base_url"] = base_url
        client = AsyncAnthropic(**kwargs)
        response = await client.messages.create(
            model="claude-haiku-3.5",
            messages=[{"role": "user", "content": "Say 'OK'"}],
            max_tokens=5,
        )
        await client.close()
        content = "".join(b.text for b in response.content if hasattr(b, "text"))
        return True, f"Model: claude-haiku-3.5, Response: {content}"
    except Exception as e:
        return False, str(e)


async def test_google():
    """Test Google Gemini API key."""
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return None, "Not configured"

    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            timeout=30,
        )
        response = await client.chat.completions.create(
            model="gemini-2.0-flash",
            messages=[{"role": "user", "content": "Say 'OK'"}],
            max_tokens=5,
        )
        await client.close()
        return True, f"Model: gemini-2.0-flash, Response: {response.choices[0].message.content}"
    except Exception as e:
        return False, str(e)


async def test_mistral():
    """Test Mistral API key."""
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        return None, "Not configured"

    try:
        from mistralai import Mistral
        client = Mistral(api_key=api_key, timeout_ms=30000)
        response = await client.chat.complete_async(
            model="mistral-small-latest",
            messages=[{"role": "user", "content": "Say 'OK'"}],
            max_tokens=5,
        )
        return True, f"Model: mistral-small-latest, Response: {response.choices[0].message.content}"
    except Exception as e:
        return False, str(e)


async def test_azure():
    """Test Azure OpenAI API key."""
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4")

    if not api_key or not endpoint:
        return None, "Not configured (need AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT)"

    try:
        from openai import AsyncAzureOpenAI
        client = AsyncAzureOpenAI(
            api_key=api_key,
            azure_endpoint=endpoint,
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2025-03-01-preview"),
            timeout=30,
        )
        response = await client.chat.completions.create(
            model=deployment,
            messages=[{"role": "user", "content": "Say 'OK'"}],
            max_tokens=5,
        )
        await client.close()
        return True, f"Deployment: {deployment}, Response: {response.choices[0].message.content}"
    except Exception as e:
        return False, str(e)


async def main():
    print("\n" + "=" * 60)
    print("  API Key Validation Test")
    print("=" * 60 + "\n")

    tests = [
        ("OpenAI", test_openai),
        ("Anthropic", test_anthropic),
        ("Google Gemini", test_google),
        ("Mistral", test_mistral),
        ("Azure OpenAI", test_azure),
    ]

    results = []
    for name, test_fn in tests:
        print(f"Testing {name}...", end=" ", flush=True)
        success, message = await test_fn()

        if success is None:
            print(f"{SKIP} {message}")
            results.append((name, "skipped"))
        elif success:
            print(f"{PASS} {message}")
            results.append((name, "passed"))
        else:
            print(f"{FAIL} {message}")
            results.append((name, "failed"))

    print("\n" + "-" * 60)
    print("Summary:")
    passed = sum(1 for _, r in results if r == "passed")
    failed = sum(1 for _, r in results if r == "failed")
    skipped = sum(1 for _, r in results if r == "skipped")
    print(f"  Passed: {passed}, Failed: {failed}, Skipped: {skipped}")

    if failed > 0:
        sys.exit(1)
    elif passed == 0:
        print("\n  No API keys configured. Set at least one:")
        print("    OPENAI_API_KEY=sk-...")
        print("    ANTHROPIC_API_KEY=sk-ant-...")
        print("    GOOGLE_API_KEY=...")
        print("    MISTRAL_API_KEY=...")
        sys.exit(1)
    else:
        print(f"\n  {PASS} All configured keys are valid!")


if __name__ == "__main__":
    asyncio.run(main())
