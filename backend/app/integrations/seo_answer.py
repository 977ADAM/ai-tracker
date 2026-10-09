"""SEO answer factory; ordinary checks retain their text-only factory."""

from app.core.config import Settings
from app.core.errors import ProviderError
from app.domain.models import Connection
from app.domain.provider_groups import validate_answer_mode
from app.domain.providers import AnswerProvider, ProviderFactory
from app.domain.seo_answer import SeoAnswer, SeoAnswerProvider, SeoConnectionSnapshot
from app.integrations.deepseek_web import DeepSeekWebClient
from app.integrations.factory import build_provider


class TextSeoProvider:
    def __init__(self, provider: AnswerProvider, model: str) -> None:
        self.provider = provider
        self.model = model

    def answer(self, prompt: str) -> SeoAnswer:
        text = self.provider.answer(prompt)
        if not isinstance(text, str) or not text.strip():
            raise ProviderError("Некорректный ответ API модели")
        return SeoAnswer(text, "text", "not_requested", (), (), self.model, None)

    def close(self) -> None:
        self.provider.close()


def build_seo_answer_provider(
    snapshot: SeoConnectionSnapshot, key: str, settings: Settings, *, text_factory: ProviderFactory | None = None,
) -> SeoAnswerProvider:
    mode = validate_answer_mode(snapshot.answer_mode, snapshot.endpoint)
    if mode == "deepseek_web":
        return DeepSeekWebClient(key, snapshot.model)
    connection = Connection(snapshot.connection_id, snapshot.name, snapshot.kind, snapshot.model,
                            endpoint=snapshot.endpoint, thinking_disabled=snapshot.thinking_disabled)
    provider = text_factory(connection, key) if text_factory else build_provider(connection, key, settings)
    return TextSeoProvider(provider, snapshot.model)
