"""
Conversation Management — conversations.py
Persistent chat history, message threading, and session context.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import uuid4


class MessageRole(Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


@dataclass
class ChatMessage:
    id: str
    conversation_id: str
    role: MessageRole
    content: str
    timestamp: str
    metadata: dict = field(default_factory=dict)


@dataclass
class Conversation:
    id: str
    user_id: str
    title: str
    created_at: str
    updated_at: str
    messages: list[ChatMessage] = field(default_factory=list)
    metadata: dict = field(default_factory=lambda: {
        "total_cost": 0.0,
        "total_tokens": 0,
        "message_count": 0,
    })
    status: str = "active"


class ConversationStore(ABC):
    @abstractmethod
    async def create(self, user_id: str, title: Optional[str] = None) -> Conversation:
        ...

    @abstractmethod
    async def get(self, conversation_id: str) -> Optional[Conversation]:
        ...

    @abstractmethod
    async def list_for_user(self, user_id: str, limit: int = 20, offset: int = 0) -> list[Conversation]:
        ...

    @abstractmethod
    async def add_message(self, conversation_id: str, role: MessageRole, content: str, metadata: Optional[dict] = None) -> ChatMessage:
        ...

    @abstractmethod
    async def get_messages(self, conversation_id: str, limit: int = 50, before_id: Optional[str] = None) -> list[ChatMessage]:
        ...

    @abstractmethod
    async def update_title(self, conversation_id: str, title: str) -> Conversation:
        ...

    @abstractmethod
    async def archive(self, conversation_id: str) -> bool:
        ...

    @abstractmethod
    async def delete(self, conversation_id: str) -> bool:
        ...

    @abstractmethod
    async def search(self, user_id: str, query: str, limit: int = 10) -> list[Conversation]:
        ...


class InMemoryConversationStore(ConversationStore):
    def __init__(self) -> None:
        self._conversations: dict[str, Conversation] = {}
        self._user_index: dict[str, list[str]] = {}

    async def create(self, user_id: str, title: Optional[str] = None) -> Conversation:
        now = datetime.utcnow().isoformat()
        conversation = Conversation(
            id=str(uuid4()),
            user_id=user_id,
            title=title or "New conversation",
            created_at=now,
            updated_at=now,
        )
        self._conversations[conversation.id] = conversation
        self._user_index.setdefault(user_id, []).append(conversation.id)
        return conversation

    async def get(self, conversation_id: str) -> Optional[Conversation]:
        return self._conversations.get(conversation_id)

    async def list_for_user(self, user_id: str, limit: int = 20, offset: int = 0) -> list[Conversation]:
        conv_ids = self._user_index.get(user_id, [])
        conversations = [self._conversations[cid] for cid in conv_ids if cid in self._conversations]
        conversations.sort(key=lambda c: c.updated_at, reverse=True)
        result = []
        for conv in conversations[offset:offset + limit]:
            result.append(Conversation(
                id=conv.id,
                user_id=conv.user_id,
                title=conv.title,
                created_at=conv.created_at,
                updated_at=conv.updated_at,
                messages=[],
                metadata=dict(conv.metadata),
                status=conv.status,
            ))
        return result

    async def add_message(self, conversation_id: str, role: MessageRole, content: str, metadata: Optional[dict] = None) -> ChatMessage:
        conversation = self._conversations.get(conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        message = ChatMessage(
            id=str(uuid4()),
            conversation_id=conversation_id,
            role=role,
            content=content,
            timestamp=datetime.utcnow().isoformat(),
            metadata=metadata or {},
        )
        conversation.messages.append(message)
        conversation.updated_at = message.timestamp
        conversation.metadata["message_count"] = len(conversation.messages)

        if metadata:
            if "cost_usd" in metadata:
                conversation.metadata["total_cost"] = conversation.metadata.get("total_cost", 0.0) + metadata["cost_usd"]
            if "tokens_used" in metadata:
                conversation.metadata["total_tokens"] = conversation.metadata.get("total_tokens", 0) + metadata["tokens_used"]

        if len(conversation.messages) == 1 and role == MessageRole.USER:
            conversation.title = content[:80]

        return message

    async def get_messages(self, conversation_id: str, limit: int = 50, before_id: Optional[str] = None) -> list[ChatMessage]:
        conversation = self._conversations.get(conversation_id)
        if conversation is None:
            return []

        messages = conversation.messages
        if before_id is not None:
            idx = None
            for i, msg in enumerate(messages):
                if msg.id == before_id:
                    idx = i
                    break
            if idx is not None:
                messages = messages[:idx]

        return messages[-limit:]

    async def update_title(self, conversation_id: str, title: str) -> Conversation:
        conversation = self._conversations.get(conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation {conversation_id} not found")
        conversation.title = title[:80]
        conversation.updated_at = datetime.utcnow().isoformat()
        return conversation

    async def archive(self, conversation_id: str) -> bool:
        conversation = self._conversations.get(conversation_id)
        if conversation is None:
            return False
        conversation.status = "archived"
        conversation.updated_at = datetime.utcnow().isoformat()
        return True

    async def delete(self, conversation_id: str) -> bool:
        conversation = self._conversations.pop(conversation_id, None)
        if conversation is None:
            return False
        user_ids = self._user_index.get(conversation.user_id, [])
        if conversation_id in user_ids:
            user_ids.remove(conversation_id)
        return True

    async def search(self, user_id: str, query: str, limit: int = 10) -> list[Conversation]:
        conv_ids = self._user_index.get(user_id, [])
        query_lower = query.lower()
        results = []
        for cid in conv_ids:
            conv = self._conversations.get(cid)
            if conv is None or conv.status != "active":
                continue
            for msg in conv.messages:
                if query_lower in msg.content.lower():
                    results.append(Conversation(
                        id=conv.id,
                        user_id=conv.user_id,
                        title=conv.title,
                        created_at=conv.created_at,
                        updated_at=conv.updated_at,
                        messages=[],
                        metadata=dict(conv.metadata),
                        status=conv.status,
                    ))
                    break
            if len(results) >= limit:
                break
        return results


def build_context_messages(conversation: Conversation, max_messages: int = 20) -> list[dict]:
    recent = conversation.messages[-max_messages:]
    result = []
    for msg in recent:
        if msg.role == MessageRole.SYSTEM:
            result.append({"role": "system", "content": msg.content})
        elif msg.role == MessageRole.TOOL:
            result.append({"role": "assistant", "content": f"[Tool: {msg.metadata.get('tool_name', 'unknown')}] {msg.content}"})
        elif msg.role == MessageRole.USER:
            result.append({"role": "user", "content": msg.content})
        elif msg.role == MessageRole.ASSISTANT:
            result.append({"role": "assistant", "content": msg.content})
    return result
