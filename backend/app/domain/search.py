"""Pure rules of the Yandex search branch: the region catalog and host matching.

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

INVALID_SITE = "Укажите сайт: домен или ссылку http(s)"


@dataclass(frozen=True)
class SearchDocument:
    """One result document of a search response.

    The search report keeps the SERP ``title`` as evidence and stores an empty
    string when the response has no title element.
    """

    url: str
    title: str = ""


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
