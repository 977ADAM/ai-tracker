"""The chat message scenario: one paid call, one server-owned decision.

A user message costs exactly one service-LLM call. The model names an intent and
extracts the fields it saw; it never decides whether a run starts. This module
owns that decision, and the order of its branches is the safety property of the
feature: the first match wins, so an incomplete draft always asks a question, a
run already going always refuses, and a launch happens only from the chat's own
open proposal whose parameters still equal the draft — after the store has
atomically claimed that proposal for this turn, so two overlapping confirmations
can never fund two runs. A start that raises hands the claimed proposal back, so
a configuration refusal the user can fix does not consume the confirmation.

The launch itself is `SeoService.start`, so the paid path, its configuration
refusals, and its budget stay untouched here. `ConfigurationError` and
`ValidationError` are deliberately not caught: they reach the HTTP layer with
their fixed safe text. A `ProviderError` from the model is not caught either —
its message is already safe, and the user message stays in the feed.

Connections are never part of a model answer: the draft starts from the form's
default provider, and only the proposal chips change it afterwards.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from app.core.errors import ConfigurationError, RunNotFound, ValidationError
from app.db.chat import ChatRepository
from app.domain.chat import (
    ChatDraft,
    ChatModel,
    ChatReply,
    can_launch,
    draft_from_json,
    draft_to_json,
    merge_draft,
    message_problem,
    missing_fields,
    normalize_message,
    parse_chat_reply,
    proposal_params,
    title_from_message,
)
from app.domain.chat_prompts import (
    NOTHING_TO_RUN,
    PROPOSAL_HINT,
    RUN_IN_PROGRESS,
    question_for,
    system_prompt,
    user_prompt,
)
from app.domain.seo import GENERATED_QUERY_LIMIT
from app.domain.seo_llm import LLM_NOT_CONFIGURED
from app.domain.seo_tools import MAX_MODEL_ANSWERS, MAX_SEARCH_REQUESTS
from app.service.connections import ConnectionService
from app.service.form import FormService
from app.service.seo import SeoService

# One `ChatModel` per turn, or `None` while the service LLM is not configured.
ChatClientFactory = Callable[[], ChatModel | None]


class ChatService:
    """Run one chat turn and keep the paid launch behind a confirmed proposal."""

    def __init__(
        self,
        chats: ChatRepository,
        seo: SeoService,
        connections: ConnectionService,
        form: FormService,
        client_factory: ChatClientFactory,
    ) -> None:
        self.chats = chats
        self.seo = seo
        self.connections = connections
        self.form = form
        self.client_factory = client_factory

    # -- public API ------------------------------------------------------

    async def send_message(self, chat_id: str, text: str) -> dict[str, object]:
        """Answer one user message and return the chat with this turn's messages.

        The user message is stored before the model is called, so a provider
        failure still leaves the dialogue readable. Everything after the model
        answer is the server's decision: the draft is merged and saved first, and
        then exactly one branch of `_decide` runs.
        """
        chat = self.chats.chat(chat_id)
        problem = message_problem(text)
        if problem is not None:
            raise ValidationError(problem)
        client = self.client_factory()
        if client is None:
            raise ConfigurationError(LLM_NOT_CONFIGURED)

        message = normalize_message(text)
        first_message = not self.chats.messages(chat_id, limit=1)["items"]
        available = self.configured_connection_ids()
        draft = self._seeded_draft(chat["draft"])

        user_message = self.chats.append_message(chat_id, "user", "text", message, None)
        if first_message:
            self.chats.set_title(chat_id, title_from_message(message))

        answer = await client.complete(
            system_prompt(draft_to_json(draft), missing_fields(draft, available)),
            user_prompt(message),
        )
        reply = parse_chat_reply(answer)
        draft = merge_draft(draft, reply.params)
        self.chats.save_draft(chat_id, draft_to_json(draft))
        messages = await self._decide(chat, draft, reply, available)
        return {"chat": self.chat_summary(chat_id), "messages": [user_message, *messages]}

    def chat_summary(self, chat_id: str) -> dict[str, object]:
        """Return the list view of one chat: its title, age, and running flag."""
        chat = self.chats.chat(chat_id)
        return {
            "id": chat["id"],
            "title": chat["title"],
            "updated_at": chat["updated_at"],
            "running": self._is_running(chat),
        }

    def configured_connection_ids(self) -> tuple[str, ...]:
        """Return the IDs of the connections that carry an API key, in list order."""
        return tuple(
            str(item["id"]) for item in self.connections.list_public() if item.get("configured")
        )

    def default_connection_ids(self) -> tuple[str, ...]:
        """Return the connections the form marks by default, as the chips show them."""
        return tuple(str(item) for item in self.form.build()["default_provider_ids"])

    # -- the decision ----------------------------------------------------

    async def _decide(
        self,
        chat: Mapping[str, object],
        draft: ChatDraft,
        reply: ChatReply,
        available: Sequence[str],
    ) -> list[dict]:
        """Apply the branch order of the design and return the new feed messages.

        The order is the rule: a confirmation without a proposal never reaches the
        launch check, an incomplete draft always resets the proposal, a live run
        always wins over a new proposal, and a launch requires the stored proposal
        to match the draft exactly and the store to hand this turn the claim on
        it. Any other answer builds a fresh proposal, so "да" written together
        with new parameters is not a confirmation.
        """
        chat_id = str(chat["id"])
        missing = missing_fields(draft, available)
        running = self._is_running(chat)
        previous_id = chat["pending_proposal_id"]
        previous = self._proposal_payload(previous_id)

        if reply.intent == "confirm" and previous_id is None and missing:
            return [self._text_message(chat_id, NOTHING_TO_RUN)]
        if missing:
            self._supersede(previous_id, previous)
            self.chats.set_pending_proposal(chat_id, None)
            return [self._text_message(chat_id, reply.reply or question_for(missing[0]))]
        if running:
            return [self._text_message(chat_id, RUN_IN_PROGRESS)]
        if reply.intent == "confirm" and can_launch(previous, draft, running=False):
            return await self._start_run(chat_id, draft, previous_id, previous)
        return self._propose(chat_id, draft, previous_id, previous, reply.reply)

    async def _start_run(
        self,
        chat_id: str,
        draft: ChatDraft,
        proposal_id: str | None,
        proposal: Mapping[str, object] | None,
    ) -> list[dict]:
        """Claim the confirmed proposal, start the paid run, and close it as used.

        `can_launch` only proved that the proposal this turn *read* was pending and
        matched the draft; that read happened before the model call, so another
        turn may have consumed the proposal since. The claim is the authority: one
        conditional update in the store picks exactly one winner, and a loser
        answers that the run is under way instead of funding a second one.

        A start that raises — `ConfigurationError` and `ValidationError` from the
        paid path are the expected ones — gives the claimed proposal back before
        the error continues to the HTTP layer: the user can fix the setting and
        confirm the same card again. Only a free pointer is written back, so the
        restore never fights the claim for the right to start.

        The parameters come from the draft, which `can_launch` has just proven
        equal to the stored proposal: the model answer can name a run, but only
        the server can create one, and only from the parameters the user saw. The
        run card is the whole answer of this turn — the model's sentence is not
        shown, because the card already reports what is happening.
        """
        if proposal_id is None or not self.chats.claim_proposal(chat_id, proposal_id):
            return [self._text_message(chat_id, RUN_IN_PROGRESS)]
        try:
            started = await self.seo.start(proposal_params(draft))
        except BaseException:
            self.chats.restore_proposal(chat_id, proposal_id)
            raise
        analysis_id = str(started["id"])
        self.chats.set_active_analysis(chat_id, analysis_id)
        if proposal_id is not None and proposal is not None:
            self.chats.update_message_payload(proposal_id, {**proposal, "status": "confirmed"})
        self.chats.set_pending_proposal(chat_id, None)
        return [
            self.chats.append_message(chat_id, "assistant", "run", None, {"analysis_id": analysis_id})
        ]

    def _propose(
        self,
        chat_id: str,
        draft: ChatDraft,
        proposal_id: str | None,
        proposal: Mapping[str, object] | None,
        reply: str,
    ) -> list[dict]:
        """Supersede the old proposal and show a fresh one with the current draft.

        The assistant's own text carries the confirmation hint, because no run may
        start from a proposal card alone: the words of the next message decide.
        """
        self._supersede(proposal_id, proposal)
        hint = f"{reply} {PROPOSAL_HINT}" if reply else PROPOSAL_HINT
        messages = [self._text_message(chat_id, hint)]
        created = self.chats.append_message(chat_id, "assistant", "proposal", None, self._proposal(draft))
        self.chats.set_pending_proposal(chat_id, created["id"])
        messages.append(created)
        return messages

    # -- draft and proposal helpers --------------------------------------

    def _seeded_draft(self, stored: object) -> ChatDraft:
        """Read the stored draft, filling connections from the form's defaults.

        Connections are never asked for in words, so a chat that never named one
        would otherwise stay incomplete forever. The seeding only fills an empty
        list: a chip choice of the user is never overwritten.
        """
        draft = draft_from_json(stored)
        if draft.connection_ids:
            return draft
        defaults = self.default_connection_ids()
        return merge_draft(draft, {"connection_ids": list(defaults)}) if defaults else draft

    @staticmethod
    def _proposal(draft: ChatDraft) -> dict[str, object]:
        """Return the stored proposal: the draft, its status, and the run estimate."""
        return {
            "status": "pending",
            **proposal_params(draft),
            "search_upper": MAX_SEARCH_REQUESTS,
            "model_upper": MAX_MODEL_ANSWERS,
            "generated_limit": GENERATED_QUERY_LIMIT,
        }

    def _proposal_payload(self, proposal_id: object) -> Mapping[str, object] | None:
        """Return the payload of the open proposal, or `None` when there is none."""
        if not isinstance(proposal_id, str) or not proposal_id:
            return None
        payload = self.chats.message(proposal_id)["payload"]
        return payload if isinstance(payload, Mapping) else None

    def _supersede(self, proposal_id: str | None, proposal: Mapping[str, object] | None) -> None:
        """Mark the open proposal as outdated, when one is open."""
        if proposal_id is None or proposal is None:
            return
        self.chats.update_message_payload(proposal_id, {**proposal, "status": "superseded"})

    def _text_message(self, chat_id: str, text: str) -> dict:
        """Append one assistant sentence to the feed."""
        return self.chats.append_message(chat_id, "assistant", "text", text, None)

    def _is_running(self, chat: Mapping[str, object]) -> bool:
        """Report whether the run the chat started is still going.

        A run deleted from the store — with its chat or by hand — is not a chat's
        run any more, so an unknown analysis reads as "not running" instead of
        failing the whole turn.
        """
        analysis_id = chat.get("active_analysis_id")
        if not isinstance(analysis_id, str) or not analysis_id:
            return False
        try:
            return self.seo.snapshot(analysis_id).get("status") == "running"
        except RunNotFound:
            return False


__all__ = ["ChatService"]
