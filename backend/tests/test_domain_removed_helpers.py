"""Names that only the retired flows used are gone."""

from app.core import database
from app.domain import limits, matching, models


def test_the_retired_domain_names_are_gone():
    assert not hasattr(matching, "mentions_brand")
    assert not hasattr(limits, "LIMITS")
    assert not hasattr(limits, "MAX_PROMPTS_TEXT_LENGTH")
    for name in ("CheckInput", "CheckReport", "CheckSummary", "PromptResult", "ProviderCheck"):
        assert not hasattr(models, name)


def test_the_retired_database_helpers_are_gone():
    assert not hasattr(database, "require_project")
    assert not hasattr(database.Connection, "executemany")
