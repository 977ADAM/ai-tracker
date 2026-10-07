"""Pure chat dialogue rules: the draft, its gaps, the proposal, and the launch right.

The chat collects the same five parameters the SEO form used to ask for. This
module owns the vocabulary of that draft — what it holds, what is still missing,
which run parameters a proposal carries, and whether a proposal may start a run.
It performs no I/O: `db.chat` stores the draft, `service.chat` calls these
functions, and the field rules reuse `domain.seo` so the chat and the run agree
on what a usable parameter is. The connection count is checked here, while
"configured" comes from the caller as `available_connections`.

The module also declares the service-model contract the chat calls and parses
its answer. The model names the intent and extracts the fields; it never decides
whether a run starts, and its `params` can only carry the fields the chat itself
collects.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Literal, Protocol, runtime_checkable

from app.core.errors import ValidationError
from app.domain.matching import normalize_text
from app.domain.seo import (
    MAX_CONNECTIONS,
    MAX_QUERY_LENGTH,
    MAX_QUERY_WORDS,
    MAX_SERVICE_LENGTH,
    MAX_SERVICES,
    MAX_SPHERE_LENGTH,
    SEED_COUNT,
    url_problem,
)
from app.domain.seo_llm import parse_json_object

MAX_MESSAGE_LENGTH = 4000
MAX_REPLY_LENGTH = 2000
MAX_TITLE_LENGTH = 80
DEFAULT_TITLE = "Новый чат"

# The intents the service model may name. `confirm` is only a request: whether a
# run starts is decided by `can_launch`, not by this word.
ChatIntent = Literal["message", "confirm"]

# The order the assistant asks for the missing fields. Connections are not a
# question of their own: they start from the configured defaults and change with
# the proposal chips, so their absence is reported as the `services` gap.
FIELD_ORDER = ("url", "sphere", "seeds", "services")

EMPTY_MESSAGE = "Введите сообщение"
MESSAGE_TOO_LONG = f"Сообщение не должно быть длиннее {MAX_MESSAGE_LENGTH} символов"
# One fixed phrase for every malformed answer: the paid call is spent, but the
# draft, the proposal, and the run stay as they were, and no model text leaks out.
CHAT_PARSE_FAILED = "Не удалось разобрать сообщение. Переформулируйте, пожалуйста."

# The fields the chat collects and the model may fill. The draft also stores
# `connection_ids`, but those change with the proposal chips only, so they are
# never part of a parsed model answer.
_REPLY_SCALARS = ("url", "sphere")
_REPLY_LISTS = ("seeds", "services")

_SCALAR_FIELDS = _REPLY_SCALARS
_LIST_FIELDS = (*_REPLY_LISTS, "connection_ids")


@dataclass(frozen=True)
class ChatDraft:
    """The chat parameters accumulated from the conversation so far.

    Scalars are stored trimmed and may be empty; the three lists keep the order
    the user stated and may hold values the run would still refuse. Completeness
    is never a property of the dataclass — `missing_fields` decides it.
    """

    url: str = ""
    sphere: str = ""
    seeds: tuple[str, ...] = ()
    services: tuple[str, ...] = ()
    connection_ids: tuple[str, ...] = ()


def draft_to_json(draft: ChatDraft) -> dict[str, object]:
    """Return the storage shape of a draft: five fields, lists for the lists.

    JSON has no tuples, so the three sequence fields become lists; a stored
    draft round-trips through `draft_from_json` unchanged.
    """
    return {
        "url": draft.url,
        "sphere": draft.sphere,
        "seeds": list(draft.seeds),
        "services": list(draft.services),
        "connection_ids": list(draft.connection_ids),
    }


def draft_from_json(value: object) -> ChatDraft:
    """Read the stored draft shape, treating a missing or junk field as empty.

    The expected shape is the one `ChatRepository` writes. Anything else — a
    missing dictionary, `None`, a string — reads as a fresh draft, and a
    non-string item inside a stored list is dropped, so a hand-edited row can
    never break the dataclass.
    """
    if not isinstance(value, Mapping):
        return ChatDraft()
    return ChatDraft(
        url=_text(value.get("url")),
        sphere=_text(value.get("sphere")),
        seeds=_texts(value.get("seeds")),
        services=_texts(value.get("services")),
        connection_ids=_texts(value.get("connection_ids")),
    )


def merge_draft(draft: ChatDraft, params: Mapping[str, object]) -> ChatDraft:
    """Fold the fields named in one message into the draft.

    A non-empty scalar replaces the stored one; a non-empty list replaces the
    stored list whole; an absent, empty, or mistyped value leaves the draft
    untouched. Values are trimmed but not checked against the field rules: an
    unusable value stays so the next message can complete it, and
    `missing_fields` keeps reporting it as missing.
    """
    if not isinstance(params, Mapping):
        return draft
    changes: dict[str, object] = {}
    for field in _SCALAR_FIELDS:
        text = _text(params.get(field))
        if text:
            changes[field] = text
    for field in _LIST_FIELDS:
        items = _texts(params.get(field))
        if items:
            changes[field] = items
    return replace(draft, **changes) if changes else draft


def missing_fields(draft: ChatDraft, available_connections: Sequence[str]) -> tuple[str, ...]:
    """Return the fields the assistant still has to ask for, in question order.

    The rules are the run's field rules for the URL, sphere, key queries,
    services, and the connection count; the caller supplies the configured
    connection IDs. Connections share the `services` entry: they are never asked
    for in words, so their absence is reported as that one gap. An empty tuple is
    a promise: `normalize_seo_request(proposal_params(draft))` then accepts, so a
    confirmed proposal can never be refused by `SeoService.start`.
    """
    gaps = {
        "url": url_problem(draft.url) is not None,
        "sphere": not 1 <= len(draft.sphere.strip()) <= MAX_SPHERE_LENGTH,
        "seeds": not _seeds_valid(draft.seeds),
        "services": (
            not _services_valid(draft.services)
            or not _connections_valid(draft.connection_ids, available_connections)
        ),
    }
    return tuple(field for field in FIELD_ORDER if gaps[field])


def message_problem(text: object) -> str | None:
    """Return why a user message cannot be accepted, or `None` when it can.

    A message is user text: anything but a non-blank string, or a string longer
    than the fixed limit, is refused before the assistant is paid to read it.
    """
    if not isinstance(text, str):
        return EMPTY_MESSAGE
    message = text.strip()
    if not message:
        return EMPTY_MESSAGE
    if len(message) > MAX_MESSAGE_LENGTH:
        return MESSAGE_TOO_LONG
    return None


def normalize_message(text: str) -> str:
    """Return the message as it is stored in the feed and sent to the model."""
    return text.strip()


def title_from_message(text: str) -> str:
    """Return the chat title: the first message trimmed to the fixed limit."""
    title = _text(text)
    return title[:MAX_TITLE_LENGTH] if title else DEFAULT_TITLE


def proposal_params(draft: ChatDraft) -> dict[str, object]:
    """Return exactly the five run fields of a draft, ready for `SeoService.start`.

    The proposal stores this shape, so a confirmed proposal can be launched
    without a second look at the model answer that produced it.
    """
    return draft_to_json(draft)


def proposal_matches(payload: Mapping[str, object], draft: ChatDraft) -> bool:
    """Report whether a stored proposal carries the current draft's parameters.

    Every one of the five fields must match: a scalar is compared by value and a
    list by its items in order, so retyping even one parameter supersedes the
    proposal instead of confirming it.
    """
    if not isinstance(payload, Mapping):
        return False
    return all(_same(payload.get(field), expected) for field, expected in draft_to_json(draft).items())


def can_launch(proposal: Mapping[str, object] | None, draft: ChatDraft, running: bool) -> bool:
    """Report whether the chat may start its run right now.

    A run starts only from the chat's own open proposal: the proposal has to
    exist, still be `pending`, carry exactly the draft's parameters, and no run
    may already be going. The caller has already refused an incomplete draft, so
    the parameters are known to be usable.
    """
    if running or not isinstance(proposal, Mapping):
        return False
    if proposal.get("status") != "pending":
        return False
    return proposal_matches(proposal, draft)


@runtime_checkable
class ChatModel(Protocol):
    """The service model of the dialogue: one system and one user message in, text out.

    The contract is structural, so the real `SeoLlmClient` satisfies it without
    any integration import in this package.
    """

    async def complete(self, system: str, user: str) -> str:
        """Answer one chat prompt with the model's raw text."""
        ...


@dataclass(frozen=True)
class ChatReply:
    """One parsed service-model answer: what to say, what it means, what it extracted.

    `params` holds only the four fields the chat collects; it is empty when the
    message named no parameter. It is raw input for `merge_draft`, not a draft.
    """

    reply: str
    intent: ChatIntent
    params: Mapping[str, object]


def parse_chat_reply(answer: str) -> ChatReply:
    """Read one model answer into the strict chat contract, or fail closed.

    The answer must be a JSON object with a string `reply` and an `intent` of
    `message` or `confirm`; `params` is optional and may only name `url`,
    `sphere`, `seeds`, and `services`. A mistyped known field fails the whole
    answer, while unknown keys inside `params` — `connection_ids` included — are
    ignored: connections change with the proposal chips, never with model text.
    Every failure reports the one fixed phrase, so no model or provider detail
    reaches the feed.
    """
    payload = _reply_payload(answer)
    reply = payload.get("reply")
    if not isinstance(reply, str):
        raise ValidationError(CHAT_PARSE_FAILED)
    return ChatReply(
        reply=reply.strip()[:MAX_REPLY_LENGTH],
        intent=_reply_intent(payload.get("intent")),
        params=_reply_params(payload.get("params", {})),
    )


def _reply_payload(answer: str) -> dict[str, object]:
    """Return the JSON object of an answer, reporting the chat's fixed failure phrase."""
    try:
        return parse_json_object(answer)
    except ValidationError as exc:
        raise ValidationError(CHAT_PARSE_FAILED) from exc


def _reply_intent(value: object) -> ChatIntent:
    """Return the named intent, refusing every other word and type."""
    if value == "message":
        return "message"
    if value == "confirm":
        return "confirm"
    raise ValidationError(CHAT_PARSE_FAILED)


def _reply_params(value: object) -> dict[str, object]:
    """Return the known fields of `params`, ignoring unknown keys and failing on a type.

    An optional `params` key defaults to an empty object; anything that is not an
    object is a parse failure, as is a known field of the wrong type. A list
    field must be a list of strings: partially understood parameters could
    otherwise rewrite the draft in a way the user never stated.
    """
    if not isinstance(value, Mapping):
        raise ValidationError(CHAT_PARSE_FAILED)
    params: dict[str, object] = {}
    for field in _REPLY_SCALARS:
        if field in value:
            text = value[field]
            if not isinstance(text, str):
                raise ValidationError(CHAT_PARSE_FAILED)
            params[field] = text
    for field in _REPLY_LISTS:
        if field in value:
            items = value[field]
            if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
                raise ValidationError(CHAT_PARSE_FAILED)
            params[field] = list(items)
    return params


def _text(value: object) -> str:
    """Return a trimmed string, or an empty string for any other value."""
    return value.strip() if isinstance(value, str) else ""


def _texts(value: object) -> tuple[str, ...]:
    """Return the non-empty trimmed strings of a stored list, dropping the rest."""
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(text for text in (_text(item) for item in value) if text)


def _seeds_valid(seeds: Sequence[str]) -> bool:
    """Exactly `SEED_COUNT` distinct non-empty key queries inside the run's limits."""
    texts = tuple(_text(seed) for seed in seeds)
    if len(texts) != SEED_COUNT or not all(texts):
        return False
    if any(len(text) > MAX_QUERY_LENGTH or len(text.split()) > MAX_QUERY_WORDS for text in texts):
        return False
    return _distinct(texts)


def _services_valid(services: Sequence[str]) -> bool:
    """One to `MAX_SERVICES` distinct non-empty services of at most `MAX_SERVICE_LENGTH`."""
    texts = tuple(_text(service) for service in services)
    if not 1 <= len(texts) <= MAX_SERVICES or not all(texts):
        return False
    if not all(len(text) <= MAX_SERVICE_LENGTH for text in texts):
        return False
    return _distinct(texts)


def _connections_valid(connection_ids: Sequence[str], available_connections: Sequence[str]) -> bool:
    """One to `MAX_CONNECTIONS` distinct non-empty IDs, each one configured."""
    ids = tuple(_text(connection_id) for connection_id in connection_ids)
    if not 1 <= len(ids) <= MAX_CONNECTIONS or not all(ids):
        return False
    if len(set(ids)) != len(ids):
        return False
    known = {_text(connection_id) for connection_id in available_connections}
    return all(connection_id in known for connection_id in ids)


def _distinct(values: Sequence[str]) -> bool:
    """Compare strings the same way the run does: casefolded and whitespace-folded."""
    keys = [normalize_text(value) for value in values]
    return len(set(keys)) == len(keys)


def _same(stored: object, expected: object) -> bool:
    """Compare one stored proposal field with the draft's value."""
    if isinstance(expected, list):
        return isinstance(stored, (list, tuple)) and list(stored) == expected
    return isinstance(stored, str) and stored == expected
