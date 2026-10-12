"""The search service is only the gateway holder the settings and measurement need."""

import pytest

from app.service.search import SearchService


@pytest.mark.anyio
async def test_the_service_only_holds_the_configured_gateway():
    service = SearchService(None)
    assert service.gateway is None
    assert service.enabled is True  # Настройки по умолчанию считают Яндекс доступным.
    service.configure("gateway-sentinel", True)
    assert service.gateway == "gateway-sentinel"
    service.configure(None, False)
    assert service.enabled is False
    await service.close()


def test_the_job_queue_is_gone():
    for name in ("start", "snapshot", "abort"):
        assert not hasattr(SearchService, name)
