from audio_worker.backends.sensevoice import _parse_sensevoice


def test_parse_tagged_sensevoice_text() -> None:
    raw = [{"text": "<|zh|><|NEUTRAL|><|Speech|>今天天气不错"}]
    text, emotion, events = _parse_sensevoice(raw)
    assert "今天天气不错" in text
    assert emotion == "neutral"
    assert "Speech" in events


def test_parse_empty() -> None:
    text, emotion, events = _parse_sensevoice([])
    assert text == ""
    assert emotion is None
    assert events == []
