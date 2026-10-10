"""Project setup uses provider search, never crawls the brand's website."""
import asyncio
import json

import pytest

from app.core.errors import ProviderError
from app.domain.matching import mentions_phrase
from app.domain.seo_answer import Citation, SeoAnswer
from app.service.project_generation import ProjectGenerationService
from tests.test_projects_measurements import project


@pytest.mark.parametrize('kind', ['description', 'queries', 'competitors'])
def test_generation_uses_native_search_and_returns_sources(kind):
    calls = []
    class Projects:
        def get(self, id):
            return project(brand_description='Сеть пиццерий')
    class Search:
        async def complete_with_search(self, system, user):
            calls.append((system, json.loads(user)))
            proposal = {'description': {'brand_description': 'Сеть пиццерий', 'brand_aliases': ['Додо Пицца']}, 'queries': {'queries': [{'text': 'Где заказать пиццу?'}]}, 'competitors': {'competitors': []}}[kind]
            return SeoAnswer(json.dumps(proposal), 'deepseek_web', 'completed', (), (Citation('https://example.ru/about', 'О компании', None, 0, 1),), 'deepseek-flash', 1)
    class Settings:
        def build_search_client(self):
            return Search()
    result = asyncio.run(ProjectGenerationService(Projects(), Settings()).generate('p1', kind))
    assert len(calls) == 1
    assert 'pages' not in calls[0][1]
    assert result['sources'] == [{'url': 'https://example.ru/about', 'title': 'О компании'}]
    assert result['search_status'] == 'completed'


def test_search_failure_never_falls_back_to_model_knowledge():
    class Projects:
        def get(self, id):
            return project(brand_description='Сеть пиццерий')
    class Search:
        async def complete_with_search(self, system, user):
            raise ProviderError('Поиск недоступен')
    class Settings:
        def build_search_client(self):
            return Search()
    with pytest.raises(ProviderError, match='Поиск недоступен'):
        asyncio.run(ProjectGenerationService(Projects(), Settings()).generate('p1', 'queries'))


@pytest.mark.parametrize('answer,brand,expected', [
    ('Рекомендуем Додо Пицца.', 'додопицца', True),
    ('Рекомендуем Додопицца.', 'Додо Пицца', True),
    ('Супердодопицца', 'додопицца', False),
    ('Авитоавто', 'Авито', False),
])
def test_brand_spacing_preserves_word_boundaries(answer, brand, expected):
    assert mentions_phrase(answer, brand) is expected
