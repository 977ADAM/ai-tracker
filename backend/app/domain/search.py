"""Pure rules of the Yandex search branch: request limits, regions, and host matching.

The target site is entered as a hostname or an HTTP(S) URL; only its host takes
part in matching, so scheme, path, query, and port never influence the result.
A host matches itself and its subdomains, never a lookalike suffix.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from app.core.errors import ValidationError
from app.domain.limits import LIMITS, MAX_PROMPTS_TEXT_LENGTH

MAX_SEARCH_PROMPT_LENGTH = 400
MAX_SEARCH_PROMPT_WORDS = 40
MAX_REGIONS = 5
TOP_RESULTS = 10

ALLOWED_SCHEMES = ("http", "https")
MAX_HOST_LENGTH = 253
MAX_LABEL_LENGTH = 63

# Frequently used Yandex region IDs. Only documented IDs are exposed; the names
# follow the Yandex reference (https://yandex.ru/dev/webmaster/doc/ru/reference/feeds-regions).
REGIONS: tuple[tuple[int, str], ...] = (
    (1, "Москва и Московская область"),
    (213, "Москва"),
    (2, "Санкт-Петербург"),
    (54, "Екатеринбург"),
    (65, "Новосибирск"),
    (43, "Казань"),
    (47, "Нижний Новгород"),
    (39, "Ростов-на-Дону"),
    (35, "Краснодар"),
    (239, "Сочи"),
    (172, "Уфа"),
    (28, "Махачкала"),
    (1106, "Грозный"),
    (225, "Россия"),
)

KNOWN_REGION_IDS = frozenset(region_id for region_id, _ in REGIONS)

INVALID_REQUEST = "Некорректный запрос"
INVALID_SITE = "Укажите сайт: домен или ссылку http(s)"
INVALID_QUESTIONS = "Укажите от 1 до 20 вопросов"
INVALID_QUESTION_LENGTH = f"Каждый вопрос для поиска Яндекса должен содержать от 1 до {MAX_SEARCH_PROMPT_LENGTH} символов"
INVALID_QUESTION_WORDS = f"Каждый вопрос для поиска Яндекса должен содержать не более {MAX_SEARCH_PROMPT_WORDS} слов"
INVALID_REGIONS = f"Выберите от 1 до {MAX_REGIONS} разных регионов"
INVALID_REGION_TARGETS = "Выберите поддерживаемую поисковую систему для каждого региона"
SEARCH_ENGINES = frozenset({"yandex"})


@dataclass(frozen=True)
class SearchInput:
    """A normalized search request: the entered site, its host, and the paid-run scope."""

    domain: str
    host: str
    prompts: tuple[str, ...]
    regions: tuple[int, ...]
    engines: tuple[str, ...]

    @property
    def request_count(self) -> int:
        """How many paid Yandex requests this run submits."""
        return len(self.prompts) * len(self.regions)


@dataclass(frozen=True)
class SearchDocument:
    """One result document of a search response. Only its URL is needed."""

    url: str


class SearchGateway(Protocol):
    """Outbound port: submit one question for one region, then read its operation."""

    async def submit(self, prompt: str, region: int) -> str: ...

    async def result(self, operation_id: str) -> tuple[SearchDocument, ...] | None: ...


def normalize_search_host(value: str) -> str:
    """Return the ASCII host of a hostname or HTTP(S) URL, or raise ValidationError."""
    candidate = value if "://" in value else f"http://{value}"
    try:
        parsed = urlsplit(candidate)
        _port = parsed.port  # a malformed or out-of-range port raises here
    except ValueError as exc:
        raise ValidationError(INVALID_SITE) from exc
    if parsed.scheme not in ALLOWED_SCHEMES or parsed.username or parsed.password:
        raise ValidationError(INVALID_SITE)
    return _host(parsed.hostname or "")


def result_url_host(value: str) -> str | None:
    """Return the host of a result URL, or None when it cannot match any site."""
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme not in ALLOWED_SCHEMES:
        return None
    try:
        return _host(parsed.hostname or "")
    except ValidationError:
        return None


def first_matching_result(host: str, documents: Sequence[SearchDocument]) -> tuple[int, str] | None:
    """Return the rank and URL of the first of ten results on the host or its subdomains."""
    target = host.strip().rstrip(".").lower()
    if not target:
        return None
    for position, document in enumerate(documents[:TOP_RESULTS], start=1):
        result_host = result_url_host(document.url)
        if result_host is not None and (result_host == target or result_host.endswith(f".{target}")):
            return position, document.url
    return None


def normalize_search_request(payload: object) -> SearchInput:
    """Validate the site, 1..20 questions of at most 400 characters, and 1..5 regions."""
    if not isinstance(payload, dict):
        raise ValidationError(INVALID_REQUEST)

    domain = payload.get("domain")
    if not isinstance(domain, str) or not domain.strip() or len(domain.strip()) > LIMITS["max_domain_length"]:
        raise ValidationError(INVALID_SITE)
    site = domain.strip()

    regions = _normalize_regions(payload.get("regions"))
    return SearchInput(
        domain=site,
        host=normalize_search_host(site),
        prompts=_normalize_prompts(payload),
        regions=regions,
        engines=_normalize_region_targets(payload.get("region_targets"), regions),
    )


def _normalize_region_targets(value: object, regions: tuple[int, ...]) -> tuple[str, ...]:
    """Validate the selected engine for every requested region, defaulting old clients to Yandex."""
    if value is None:
        return ("yandex",) * len(regions)
    if not isinstance(value, list) or len(value) != len(regions):
        raise ValidationError(INVALID_REGION_TARGETS)
    targets: dict[int, str] = {}
    for item in value:
        if not isinstance(item, dict):
            raise ValidationError(INVALID_REGION_TARGETS)
        region, engine = item.get("region"), item.get("engine")
        if isinstance(region, bool) or not isinstance(region, int) or not isinstance(engine, str) or engine not in SEARCH_ENGINES:
            raise ValidationError(INVALID_REGION_TARGETS)
        if region in targets:
            raise ValidationError(INVALID_REGION_TARGETS)
        targets[region] = engine
    if set(targets) != set(regions):
        raise ValidationError(INVALID_REGION_TARGETS)
    return tuple(targets[region] for region in regions)


def _host(hostname: str) -> str:
    """Normalize an extracted hostname to lowercase ASCII labels."""
    host = hostname.rstrip(".").lower()
    labels = host.split(".")
    if len(labels) < 2 or len(host) > MAX_HOST_LENGTH:
        raise ValidationError(INVALID_SITE)
    encoded: list[str] = []
    for label in labels:
        if (
            not label
            or len(label) > MAX_LABEL_LENGTH
            or label.startswith("-")
            or label.endswith("-")
            or not all(character.isalnum() or character == "-" for character in label)
        ):
            raise ValidationError(INVALID_SITE)
        try:
            ascii_label = label.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise ValidationError(INVALID_SITE) from exc
        if len(ascii_label) > MAX_LABEL_LENGTH:
            raise ValidationError(INVALID_SITE)
        encoded.append(ascii_label)
    return ".".join(encoded)


def _normalize_prompts(payload: dict) -> tuple[str, ...]:
    """Read the question list from `prompts_text` (one per line) or from `prompts`."""
    prompts = payload.get("prompts")
    if "prompts_text" in payload:
        text = payload["prompts_text"]
        if not isinstance(text, str) or len(text) > MAX_PROMPTS_TEXT_LENGTH:
            raise ValidationError(INVALID_REQUEST)
        prompts = [line.strip() for line in text.splitlines() if line.strip()]

    if not isinstance(prompts, list) or not 1 <= len(prompts) <= LIMITS["max_prompts"]:
        raise ValidationError(INVALID_QUESTIONS)

    normalized: list[str] = []
    for prompt in prompts:
        if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= MAX_SEARCH_PROMPT_LENGTH:
            raise ValidationError(INVALID_QUESTION_LENGTH)
        if len(prompt.split()) > MAX_SEARCH_PROMPT_WORDS:
            raise ValidationError(INVALID_QUESTION_WORDS)
        normalized.append(prompt.strip())
    return tuple(normalized)


def _normalize_regions(value: object) -> tuple[int, ...]:
    """Keep 1..5 distinct catalog IDs; a paid request is never sent for anything else."""
    if (
        not isinstance(value, list)
        or not 1 <= len(value) <= MAX_REGIONS
        or any(isinstance(item, bool) or not isinstance(item, int) or item not in KNOWN_REGION_IDS for item in value)
        or len(value) != len(set(value))
    ):
        raise ValidationError(INVALID_REGIONS)
    return tuple(value)
