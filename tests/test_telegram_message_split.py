import pytest
from telegram.error import TimedOut

from bot.handlers import telegram
from bot.handlers.telegram import (
    TELEGRAM_SAFE_MESSAGE_LIMIT,
    _reply_text,
    _split_telegram_message,
)


def test_split_telegram_message_keeps_chunks_under_safe_limit():
    text = "\n\n".join(f"Día {idx}: " + ("sentadilla " * 70) for idx in range(20))

    chunks = _split_telegram_message(text)

    assert len(chunks) > 1
    assert all(len(chunk) <= TELEGRAM_SAFE_MESSAGE_LIMIT for chunk in chunks)


@pytest.mark.asyncio
async def test_reply_text_sends_long_message_in_chunks():
    class FakeMessage:
        def __init__(self):
            self.sent = []

        async def reply_text(self, text, parse_mode=None):
            self.sent.append((text, parse_mode))

    message = FakeMessage()
    text = "rutina " * 1200

    await _reply_text(message, text, parse_mode="Markdown")

    assert len(message.sent) > 1
    assert all(len(text) <= TELEGRAM_SAFE_MESSAGE_LIMIT for text, _ in message.sent)
    assert {parse_mode for _, parse_mode in message.sent} == {"Markdown"}


@pytest.mark.asyncio
async def test_reply_text_swallows_telegram_timeout(monkeypatch):
    events = []
    monkeypatch.setattr(
        telegram,
        "log_event",
        lambda event, **kwargs: events.append(event),
    )

    class FakeMessage:
        async def reply_text(self, text, parse_mode=None):
            raise TimedOut("telegram timeout")

    await _reply_text(FakeMessage(), "hola")

    assert events == ["telegram_reply_timeout"]
