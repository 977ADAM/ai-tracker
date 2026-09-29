"""Null objects that keep the application bootable before it is configured.

The composition root builds the whole graph at import time, while settings such
as the SEO service LLM are resolved by the user later. A stand-in keeps that
graph complete without pretending the feature is available: it is never called,
because the service refuses an unconfigured run before it spends anything.
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatResult

from app.core.errors import ConfigurationError
from app.service.seo import LLM_NOT_CONFIGURED


class UnconfiguredAgentModel(BaseChatModel):
    """The stand-in chat model of a container without a configured service LLM.

    `SeoAgentRuntime` resolves its chat model when it is built, and the
    application must start while the SEO LLM settings are empty. This model is
    never called: `SeoService.start` refuses such a run with a safe configuration
    error before any analysis row or paid call exists.
    """

    @property
    def _llm_type(self) -> str:
        return "seo-unconfigured"

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        """Refuse the tool binding like every other call of this stand-in.

        The `BaseChatModel` default answers a binding with a bare
        `NotImplementedError`, which would hide the real reason — an
        unconfigured service LLM — from the error the run stores.
        """
        raise ConfigurationError(LLM_NOT_CONFIGURED)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        raise ConfigurationError(LLM_NOT_CONFIGURED)
