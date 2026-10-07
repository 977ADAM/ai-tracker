"""Pure chat dialogue rules: the draft, its gaps, the proposal, and the launch right."""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.core.errors import ValidationError
from app.domain.chat import (
    CHAT_PARSE_FAILED,
    DEFAULT_TITLE,
    FIELD_ORDER,
    MAX_MESSAGE_LENGTH,
    MAX_REPLY_LENGTH,
    MAX_TITLE_LENGTH,
    ChatDraft,
    ChatModel,
    can_launch,
    draft_from_json,
    draft_to_json,
    merge_draft,
    message_problem,
    missing_fields,
    normalize_message,
    parse_chat_reply,
    proposal_matches,
    proposal_params,
    title_from_message,
)
from app.domain.seo import (
    MAX_CONNECTIONS,
    MAX_QUERY_LENGTH,
    MAX_QUERY_WORDS,
    MAX_SERVICE_LENGTH,
    MAX_SPHERE_LENGTH,
    SEED_COUNT,
    normalize_seo_request,
)

CONNECTIONS = ("a", "b")

# The shape `ChatRepository.create_chat` writes into `seo_chats.draft`.
STORED_DEFAULT_DRAFT: dict[str, object] = {
    "url": "",
    "sphere": "",
    "seeds": [],
    "services": [],
    "connection_ids": [],
}


def test_merge_keeps_stated_fields_and_ignores_empty():
    draft = ChatDraft(url="https://a.ru", sphere="Цветы")
    merged = merge_draft(draft, {"sphere": "  ", "seeds": ["1", "2", "3"], "services": []})
    assert merged.url == "https://a.ru"
    assert merged.sphere == "Цветы"
    assert merged.seeds == ("1", "2", "3")
    assert merged.services == ()


def test_merge_replaces_a_named_scalar_and_keeps_the_rest():
    draft = ChatDraft("https://a.ru", "Цветы", ("1", "2", "3"), ("Букеты",), CONNECTIONS)
    merged = merge_draft(draft, {"url": "  https://b.ru  ", "services": ["Розы", "Пионы"]})
    assert merged.url == "https://b.ru"
    assert merged.sphere == "Цветы"
    assert merged.seeds == ("1", "2", "3")
    assert merged.services == ("Розы", "Пионы")
    assert merged.connection_ids == CONNECTIONS


def test_merge_ignores_unknown_mistyped_and_blank_values():
    draft = ChatDraft("https://a.ru", "Цветы", ("1", "2", "3"), ("Букеты",), CONNECTIONS)
    params: dict[str, object] = {
        "unknown": "нет такого поля",
        "url": 5,
        "sphere": None,
        "seeds": "1",
        "services": ["  "],
        "connection_ids": {},
    }
    assert merge_draft(draft, params) == draft
    assert merge_draft(draft, {}) == draft


def test_merge_drops_blank_items_of_a_named_list():
    merged = merge_draft(ChatDraft(), {"seeds": [" 1 ", "", "2", None, "3"]})
    assert merged.seeds == ("1", "2", "3")


def test_missing_fields_are_asked_in_order():
    assert missing_fields(ChatDraft(), CONNECTIONS) == ("url", "sphere", "seeds", "services")
    full = ChatDraft("https://a.ru", "Цветы", ("1", "2", "3"), ("Букеты",), CONNECTIONS)
    assert missing_fields(full, CONNECTIONS) == ()


def test_missing_fields_cover_the_whole_question_order():
    assert missing_fields(ChatDraft(), CONNECTIONS) == FIELD_ORDER


def test_duplicate_seeds_and_unknown_connections_are_missing():
    draft = ChatDraft("https://a.ru", "Цветы", ("1", "1", "3"), ("Букеты",), ("нет-такого",))
    assert missing_fields(draft, CONNECTIONS) == ("seeds", "services")


def test_missing_fields_rejects_a_bare_host_an_overlong_sphere_and_a_long_service():
    bare_host = ChatDraft("example.ru", "Цветы", ("1", "2", "3"), ("Букеты",), CONNECTIONS)
    assert missing_fields(bare_host, CONNECTIONS) == ("url",)

    overlong = ChatDraft(
        "https://a.ru",
        "я" * (MAX_SPHERE_LENGTH + 1),
        ("1", "2", "3"),
        ("я" * (MAX_SERVICE_LENGTH + 1),),
        CONNECTIONS,
    )
    assert missing_fields(overlong, CONNECTIONS) == ("sphere", "services")


def test_missing_fields_rejects_blank_seeds_and_services():
    blank_seeds = ChatDraft("https://a.ru", "Цветы", ("1", " ", "3"), ("Букеты",), CONNECTIONS)
    assert missing_fields(blank_seeds, CONNECTIONS) == ("seeds",)

    blank_services = ChatDraft("https://a.ru", "Цветы", ("1", "2", "3"), (" ",), CONNECTIONS)
    assert missing_fields(blank_services, CONNECTIONS) == ("services",)


def test_missing_fields_rejects_a_wrong_seed_count_and_too_many_connections():
    too_few = ChatDraft("https://a.ru", "Цветы", ("1",) * (SEED_COUNT - 1), ("Букеты",), CONNECTIONS)
    assert missing_fields(too_few, CONNECTIONS) == ("seeds",)

    too_many_seeds = ChatDraft("https://a.ru", "Цветы", ("1",) * (SEED_COUNT + 1), ("Букеты",), CONNECTIONS)
    assert missing_fields(too_many_seeds, CONNECTIONS) == ("seeds",)

    too_many = ChatDraft(
        "https://a.ru",
        "Цветы",
        ("1", "2", "3"),
        ("Букеты",),
        tuple(f"c{index}" for index in range(MAX_CONNECTIONS + 1)),
    )
    assert missing_fields(too_many, tuple(f"c{index}" for index in range(MAX_CONNECTIONS + 1))) == ("services",)

    no_connections = ChatDraft("https://a.ru", "Цветы", ("1", "2", "3"), ("Букеты",), ())
    assert missing_fields(no_connections, CONNECTIONS) == ("services",)


def test_missing_fields_reports_a_key_query_longer_than_the_run_allows():
    draft = ChatDraft(
        "https://a.ru",
        "Цветы",
        ("1", "я" * (MAX_QUERY_LENGTH + 1), "3"),
        ("Букеты",),
        CONNECTIONS,
    )
    assert missing_fields(draft, CONNECTIONS) == ("seeds",)
    with pytest.raises(ValidationError):
        normalize_seo_request(proposal_params(draft))


def test_missing_fields_reports_a_key_query_with_too_many_words():
    wordy = " ".join(f"слово{index}" for index in range(MAX_QUERY_WORDS + 1))
    draft = ChatDraft("https://a.ru", "Цветы", ("1", wordy, "3"), ("Букеты",), CONNECTIONS)
    assert missing_fields(draft, CONNECTIONS) == ("seeds",)
    with pytest.raises(ValidationError):
        normalize_seo_request(proposal_params(draft))


def test_missing_fields_reports_duplicate_key_queries():
    draft = ChatDraft("https://a.ru", "Цветы", ("1", "1", "3"), ("Букеты",), CONNECTIONS)
    assert missing_fields(draft, CONNECTIONS) == ("seeds",)
    with pytest.raises(ValidationError):
        normalize_seo_request(proposal_params(draft))


def test_missing_fields_reports_duplicate_services():
    draft = ChatDraft("https://a.ru", "Цветы", ("1", "2", "3"), ("Букеты", "Букеты"), CONNECTIONS)
    assert missing_fields(draft, CONNECTIONS) == ("services",)
    with pytest.raises(ValidationError):
        normalize_seo_request(proposal_params(draft))


def test_missing_fields_reports_duplicate_connection_ids():
    draft = ChatDraft("https://a.ru", "Цветы", ("1", "2", "3"), ("Букеты",), ("a", "a"))
    assert missing_fields(draft, CONNECTIONS) == ("services",)
    with pytest.raises(ValidationError):
        normalize_seo_request(proposal_params(draft))


def test_draft_round_trips_through_json():
    draft = ChatDraft("https://a.ru", "Цветы", ("1", "2", "3"), ("Букеты",), CONNECTIONS)
    assert draft_from_json(draft_to_json(draft)) == draft


def test_draft_to_json_uses_lists_for_the_stored_shape():
    payload = draft_to_json(ChatDraft("https://a.ru", "Цветы", ("1",), ("Букеты",), ("a",)))
    assert payload == {
        "url": "https://a.ru",
        "sphere": "Цветы",
        "seeds": ["1"],
        "services": ["Букеты"],
        "connection_ids": ["a"],
    }
    assert all(isinstance(payload[field], list) for field in ("seeds", "services", "connection_ids"))


def test_draft_from_json_reads_the_stored_default_shape():
    assert draft_from_json(STORED_DEFAULT_DRAFT) == ChatDraft()
    assert draft_from_json({}) == ChatDraft()
    assert draft_from_json(None) == ChatDraft()
    assert draft_from_json("не словарь") == ChatDraft()


def test_draft_from_json_drops_junk_values():
    stored: dict[str, object] = {
        "url": 5,
        "sphere": None,
        "seeds": "1",
        "services": [1, "ok"],
        "connection_ids": ("a", None),
    }
    assert draft_from_json(stored) == ChatDraft(services=("ok",), connection_ids=("a",))


def test_message_problem_rejects_empty_and_too_long():
    assert message_problem("   ") is not None
    assert message_problem("я" * (MAX_MESSAGE_LENGTH + 1)) is not None
    assert message_problem("проверь сайт") is None


def test_message_problem_refuses_non_text_and_accepts_the_exact_limit():
    assert message_problem("я" * MAX_MESSAGE_LENGTH) is None
    assert message_problem(None) is not None
    assert message_problem(5) is not None


def test_normalize_message_trims_the_edges():
    assert normalize_message("  проверь  сайт  ") == "проверь  сайт"


def test_title_is_trimmed_and_bounded():
    assert title_from_message("  Привет  ") == "Привет"
    assert len(title_from_message("я" * 200)) == MAX_TITLE_LENGTH
    assert title_from_message("   ") == DEFAULT_TITLE
    assert title_from_message("Привет")[:MAX_TITLE_LENGTH] == "Привет"


def test_proposal_params_has_exactly_the_five_run_fields():
    draft = ChatDraft("https://a.ru", "Цветы", ("1", "2", "3"), ("Букеты",), CONNECTIONS)
    assert proposal_params(draft) == {
        "url": "https://a.ru",
        "sphere": "Цветы",
        "seeds": ["1", "2", "3"],
        "services": ["Букеты"],
        "connection_ids": ["a", "b"],
    }


def test_proposal_params_of_a_complete_draft_pass_run_validation():
    draft = ChatDraft("https://a.ru", "Цветы", ("1", "2", "3"), ("Букеты",), CONNECTIONS)
    assert missing_fields(draft, CONNECTIONS) == ()
    request = normalize_seo_request(proposal_params(draft))
    assert request.seeds == ("1", "2", "3")
    assert request.services == ("Букеты",)
    assert request.connection_ids == CONNECTIONS


def test_no_missing_field_means_the_proposal_params_pass_run_validation():
    """The chat invariant: an empty gap tuple guarantees `SeoService.start` accepts."""
    drafts = (
        ChatDraft("https://a.ru", "Цветы", ("1", "2", "3"), ("Букеты",), CONNECTIONS),
        ChatDraft(
            "https://a.ru",
            "Цветы",
            ("купить розы", "доставка цветов", "букет на свадьбу"),
            ("Розы", "Пионы"),
            ("a",),
        ),
    )
    for draft in drafts:
        assert missing_fields(draft, CONNECTIONS) == ()
        normalize_seo_request(proposal_params(draft))


def test_proposal_matches_reads_stored_lists_and_scalars():
    draft = ChatDraft("https://a.ru", "Цветы", ("1", "2", "3"), ("Букеты",), CONNECTIONS)
    assert proposal_matches(proposal_params(draft), draft) is True
    assert proposal_matches({**proposal_params(draft), "seeds": None}, draft) is False
    assert proposal_matches({**proposal_params(draft), "url": "https://b.ru"}, draft) is False
    assert proposal_matches({}, draft) is False


def test_launch_needs_a_matching_pending_proposal():
    draft = ChatDraft("https://a.ru", "Цветы", ("1", "2", "3"), ("Букеты",), CONNECTIONS)
    proposal = {"status": "pending", **proposal_params(draft)}
    assert can_launch(proposal, draft, running=False) is True
    assert can_launch(proposal, draft, running=True) is False
    assert can_launch(proposal, replace(draft, sphere="Другое"), running=False) is False
    assert can_launch({**proposal, "status": "superseded"}, draft, running=False) is False
    assert can_launch(None, draft, running=False) is False


def test_launch_refuses_a_proposal_without_params_or_connections():
    draft = ChatDraft("https://a.ru", "Цветы", ("1", "2", "3"), ("Букеты",), CONNECTIONS)
    assert can_launch({"status": "pending"}, draft, running=False) is False
    assert can_launch({"status": "pending", **proposal_params(draft), "connection_ids": []}, draft, running=False) is False


# -- the strict answer of the service model -----------------------------------


def test_parse_reply_reads_params_and_intent():
    reply = parse_chat_reply('{"reply": "Понял", "intent": "confirm", "params": {"url": "https://a.ru"}}')
    assert reply.intent == "confirm"
    assert reply.params == {"url": "https://a.ru"}


def test_parse_reply_trims_and_defaults_missing_params():
    reply = parse_chat_reply('{"reply": "' + "я" * 3000 + '", "intent": "message"}')
    assert len(reply.reply) == MAX_REPLY_LENGTH
    assert reply.params == {}


def test_parse_reply_normalizes_an_empty_reply_for_the_question_fallback():
    """An empty reply is legal: the scenario replaces it with the field question."""
    assert parse_chat_reply('{"reply": "  ", "intent": "message"}').reply == ""
    assert parse_chat_reply('{"reply": "", "intent": "message"}').reply == ""


@pytest.mark.parametrize("answer", [
    "не json", "[]", '{"intent": "message"}', '{"reply": "ок", "intent": "старт"}',
    '{"reply": 5, "intent": "message"}', '{"reply": "ок", "intent": "message", "params": []}',
])
def test_parse_reply_fails_closed(answer):
    with pytest.raises(ValidationError):
        parse_chat_reply(answer)


def test_parse_reply_reports_the_fixed_phrase():
    with pytest.raises(ValidationError, match=CHAT_PARSE_FAILED):
        parse_chat_reply("не json")


def test_parse_reply_rejects_wrong_param_types():
    with pytest.raises(ValidationError):
        parse_chat_reply('{"reply": "ок", "intent": "message", "params": {"seeds": "1"}}')


@pytest.mark.parametrize("params", [
    '{"url": 5}', '{"sphere": null}', '{"seeds": [1]}', '{"services": {}}',
])
def test_parse_reply_rejects_every_mistyped_known_field(params):
    with pytest.raises(ValidationError):
        parse_chat_reply(f'{{"reply": "ок", "intent": "message", "params": {params}}}')


def test_parse_reply_ignores_unknown_keys_inside_params():
    reply = parse_chat_reply(
        '{"reply": "ок", "intent": "message", "params": {"url": "https://a.ru", "unknown": "x"}}'
    )
    assert reply.params == {"url": "https://a.ru"}


def test_parse_reply_ignores_a_model_supplied_connection_ids():
    """Connections change with the proposal chips only, never with a model answer."""
    reply = parse_chat_reply(
        '{"reply": "ок", "intent": "message", '
        '"params": {"connection_ids": ["чужое"], "url": "https://a.ru"}}'
    )
    assert reply.params == {"url": "https://a.ru"}
    draft = ChatDraft("https://b.ru", "Цветы", ("1", "2", "3"), ("Букеты",), CONNECTIONS)
    assert merge_draft(draft, reply.params).connection_ids == CONNECTIONS


def test_chat_model_protocol_accepts_a_conforming_client():
    class Client:
        async def complete(self, system: str, user: str) -> str:
            return "{}"

    assert isinstance(Client(), ChatModel)
