"""Strict public schemas for the SEO chat.

Every response is a projection of what `ChatRepository`/`ChatService` already
return. A message carries its stored payload as it is — the browser needs the
proposal card — while a chat summary is deliberately four fields: a list entry
never grows with the draft, the open proposal, or the run the chat named.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, StrictStr


class ChatMessageRequest(BaseModel):
    """One user message of the dialogue."""

    model_config = ConfigDict(extra="forbid")

    text: StrictStr


class ProposalUpdateRequest(BaseModel):
    """The connections of the open proposal, chosen by the card's chips."""

    model_config = ConfigDict(extra="forbid")

    connection_ids: list[StrictStr]


class ChatMessageResponse(BaseModel):
    """One stored message: its position in the feed and its free-form payload."""

    id: str
    seq: int
    role: str
    kind: str
    text: str | None
    payload: dict[str, object] | None
    created_at: str


class ChatSummaryResponse(BaseModel):
    """The list view of one chat, exactly as `ChatService.chat_summary` returns it."""

    id: str
    title: str
    updated_at: str
    running: bool


class ChatListResponse(BaseModel):
    items: list[ChatSummaryResponse]


class ChatCreatedResponse(BaseModel):
    chat: ChatSummaryResponse


class ChatDetailResponse(BaseModel):
    """One chat with a page of its feed, oldest first inside the page."""

    chat: ChatSummaryResponse
    messages: list[ChatMessageResponse]
    next_cursor: int | None


class ChatMessagesResponse(BaseModel):
    """The chat after one turn, with the messages this turn added."""

    chat: ChatSummaryResponse
    messages: list[ChatMessageResponse]


class ProposalResponse(BaseModel):
    """The chat after a proposal edit, with the updated proposal card."""

    chat: ChatSummaryResponse
    message: ChatMessageResponse
