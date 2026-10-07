"""Pure chat dialogue rules: the draft, its gaps, the proposal, and the launch right."""

from __future__ import annotations

from dataclasses import replace

from app.domain.chat import (
    DEFAULT_TITLE,
    FIELD_ORDER,
    MAX_MESSAGE_LENGTH,
    MAX_TITLE_LENGTH,
    ChatDraft,
    can_launch,
    draft_from_json,
    draft_to_json,
    merge_draft,
    message_problem,
    missing_fields,
    normalize_message,
    proposal_matches,
    proposal_params,
    title_from_message,
)
from app.domain.seo import (
    MAX_CONNECTIONS,
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
