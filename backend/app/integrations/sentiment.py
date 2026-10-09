"""One plain completion per mentioned answer; never calls tools or retries."""

from app.domain.sentiment import SYSTEM, parse_sentiment, sentiment_input


class LlmSentimentClassifier:
    def __init__(self, client, aliases=(), description=""):
        self.client = client
        self.aliases, self.description = aliases, description

    async def classify(self, brand: str, answer: str):
        return parse_sentiment(
            await self.client.complete(
                SYSTEM, sentiment_input(brand, answer, self.aliases, self.description)
            ),
            answer,
        )
