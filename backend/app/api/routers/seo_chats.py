"""Create, list, read, write, and delete SEO chats.

The router only declares routes and dependencies, and the split is the rule: the
list and the feed are read straight from the repository in the container, while
every write goes through `ChatService`, which owns the one paid call of a turn
and the decision to start a run. No handler ever sees a credential.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response

from app.api.deps import ChatServiceDep, ContainerDep
from app.api.schemas import ErrorResponse
from app.api.schemas.seo_chat import (
    ChatCreatedResponse,
    ChatDetailResponse,
    ChatListResponse,
    ChatMessageRequest,
    ChatMessagesResponse,
    ProposalResponse,
    ProposalUpdateRequest,
)
from app.domain.chat import DEFAULT_TITLE

router = APIRouter(prefix="/seo/chats", tags=["seo"])
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorResponse}, 404: {"model": ErrorResponse},
    409: {"model": ErrorResponse}, 503: {"model": ErrorResponse},
}


@router.get("", response_model=ChatListResponse, responses=ERROR_RESPONSES)
def list_chats(container: ContainerDep, chat_service: ChatServiceDep) -> dict:
    """List the chats newest first, each with its live "a run is going" flag."""
    items = [
        chat_service.chat_summary(str(chat["id"])) for chat in container.chats.list_chats()
    ]
    return {"items": items}


@router.post("", status_code=201, response_model=ChatCreatedResponse, responses=ERROR_RESPONSES)
def create_chat(container: ContainerDep, chat_service: ChatServiceDep) -> dict:
    """Create an empty chat; the first user message gives it its title."""
    chat_id = container.chats.create_chat(DEFAULT_TITLE)
    return {"chat": chat_service.chat_summary(chat_id)}


@router.get("/{chat_id}", response_model=ChatDetailResponse, responses=ERROR_RESPONSES)
def get_chat(
    container: ContainerDep, chat_service: ChatServiceDep, chat_id: str, before: int | None = None,
) -> dict:
    """Read one chat with a page of its feed; `before` asks for older messages."""
    page = container.chats.messages(chat_id, before)
    return {
        "chat": chat_service.chat_summary(chat_id),
        "messages": page["items"],
        "next_cursor": page["next_cursor"],
    }


@router.delete("/{chat_id}", status_code=204, responses=ERROR_RESPONSES)
def delete_chat(chat_service: ChatServiceDep, chat_id: str) -> Response:
    """Delete one chat and the runs it started; an active run is a conflict."""
    chat_service.delete_chat(chat_id)
    return Response(status_code=204)


@router.post("/{chat_id}/messages", response_model=ChatMessagesResponse, responses=ERROR_RESPONSES)
async def send_message(chat_service: ChatServiceDep, chat_id: str, payload: ChatMessageRequest) -> dict:
    """Answer one user message with a question, a proposal, or the paid run."""
    return await chat_service.send_message(chat_id, payload.text)


@router.put("/{chat_id}/proposal", response_model=ProposalResponse, responses=ERROR_RESPONSES)
def update_proposal(chat_service: ChatServiceDep, chat_id: str, payload: ProposalUpdateRequest) -> dict:
    """Replace the connections of the open proposal and answer with its card."""
    return chat_service.update_proposal(chat_id, payload.connection_ids)
