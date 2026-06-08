"""Unit tests for conversation management module."""

import pytest

from orchestrator_agent.conversations import (
    InMemoryConversationStore,
    MessageRole,
    build_context_messages,
)


@pytest.fixture
def store():
    return InMemoryConversationStore()


USER_ID = "user-001"


# ── Create ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_conversation(store):
    conv = await store.create(USER_ID, title="Hello")
    assert conv.id
    assert conv.user_id == USER_ID
    assert conv.title == "Hello"
    assert conv.status == "active"
    assert conv.created_at
    assert conv.updated_at


@pytest.mark.asyncio
async def test_auto_title(store):
    conv = await store.create(USER_ID)
    assert conv.title == "New conversation"
    await store.add_message(conv.id, MessageRole.USER, "What is the weather today?")
    updated = await store.get(conv.id)
    assert updated.title == "What is the weather today?"


# ── Messages ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_message(store):
    conv = await store.create(USER_ID, title="Chat")
    msg = await store.add_message(conv.id, MessageRole.USER, "hi there")
    assert msg.id
    assert msg.conversation_id == conv.id
    assert msg.role == MessageRole.USER
    assert msg.content == "hi there"
    assert msg.timestamp

    await store.add_message(conv.id, MessageRole.ASSISTANT, "hello!")
    updated = await store.get(conv.id)
    assert len(updated.messages) == 2
    assert updated.messages[1].role == MessageRole.ASSISTANT


@pytest.mark.asyncio
async def test_cost_accumulation(store):
    conv = await store.create(USER_ID, title="Costs")
    await store.add_message(conv.id, MessageRole.USER, "q1", metadata={"cost_usd": 0.01})
    await store.add_message(conv.id, MessageRole.ASSISTANT, "a1", metadata={"cost_usd": 0.02})
    updated = await store.get(conv.id)
    assert abs(updated.metadata["total_cost"] - 0.03) < 1e-9


# ── List ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_for_user(store):
    c1 = await store.create(USER_ID, title="First")
    await store.create(USER_ID, title="Second")
    # Add a message to c1 so its updated_at is newer
    await store.add_message(c1.id, MessageRole.USER, "bump")
    listing = await store.list_for_user(USER_ID)
    assert len(listing) == 2
    # c1 should come first (most recently updated)
    assert listing[0].id == c1.id


@pytest.mark.asyncio
async def test_list_excludes_messages(store):
    conv = await store.create(USER_ID, title="Has Messages")
    await store.add_message(conv.id, MessageRole.USER, "secret content")
    listing = await store.list_for_user(USER_ID)
    assert len(listing) == 1
    assert listing[0].messages == []


# ── Pagination ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_messages_pagination(store):
    conv = await store.create(USER_ID, title="Paginate")
    for i in range(10):
        await store.add_message(conv.id, MessageRole.USER, f"msg-{i}")
    messages = await store.get_messages(conv.id, limit=5)
    assert len(messages) == 5
    # Should return the last 5 messages
    assert messages[0].content == "msg-5"
    assert messages[-1].content == "msg-9"


# ── Archive & Delete ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_archive(store):
    conv = await store.create(USER_ID, title="To Archive")
    result = await store.archive(conv.id)
    assert result is True
    updated = await store.get(conv.id)
    assert updated.status == "archived"


@pytest.mark.asyncio
async def test_delete(store):
    conv = await store.create(USER_ID, title="To Delete")
    result = await store.delete(conv.id)
    assert result is True
    assert await store.get(conv.id) is None


# ── Search ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search(store):
    c1 = await store.create(USER_ID, title="Alpha")
    c2 = await store.create(USER_ID, title="Beta")
    await store.add_message(c1.id, MessageRole.USER, "Find the golden key")
    await store.add_message(c2.id, MessageRole.USER, "Nothing special here")
    results = await store.search(USER_ID, "golden")
    assert len(results) == 1
    assert results[0].id == c1.id


# ── Context builder ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_build_context_messages(store):
    conv = await store.create(USER_ID, title="Context")
    await store.add_message(conv.id, MessageRole.SYSTEM, "You are helpful.")
    await store.add_message(conv.id, MessageRole.USER, "Hello")
    await store.add_message(conv.id, MessageRole.ASSISTANT, "Hi there!")
    await store.add_message(
        conv.id, MessageRole.TOOL, "result data",
        metadata={"tool_name": "search"},
    )

    full_conv = await store.get(conv.id)
    ctx = build_context_messages(full_conv)

    assert len(ctx) == 4
    assert ctx[0] == {"role": "system", "content": "You are helpful."}
    assert ctx[1] == {"role": "user", "content": "Hello"}
    assert ctx[2] == {"role": "assistant", "content": "Hi there!"}
    assert ctx[3]["role"] == "assistant"
    assert "[Tool: search]" in ctx[3]["content"]
