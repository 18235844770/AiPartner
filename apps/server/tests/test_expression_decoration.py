import random

from app.modules.dialogue.domain.expression_decoration import decorate_reply
from app.modules.persona.domain.expression_marks import load_expression_catalog


class _Always(random.Random):
    def random(self) -> float:
        return 0.0

    def choice(self, seq):
        return sorted(seq, key=lambda item: item.mark)[0]


def test_catalog_covers_six_personas() -> None:
    catalog = load_expression_catalog()
    assert set(catalog.persona_styles) == {"ENFP", "ENFJ", "INFP", "INFJ", "INTJ", "INTP"}
    assert catalog.frequency.max_emoji_per_message == 2
    assert catalog.frequency.max_kaomoji_per_message == 1


def test_guidance_and_fact_correction_stay_plain() -> None:
    text = "我倾向先不接。开口就是催，接了多半还是那一套。😊"
    plain = decorate_reply(
        text,
        mbti_type="ENFP",
        emotion="joy",
        action="respond",
        user_text="你是觉得我应该回吗",
        rng=_Always(),
    )
    assert plain == "我倾向先不接。开口就是催，接了多半还是那一套。"
    corrected = decorate_reply(
        "现在是晚上。😄",
        mbti_type="ENFP",
        emotion="joy",
        action="respond",
        user_text="早上好",
        fact_correct=True,
        rng=_Always(),
    )
    assert corrected == "现在是晚上。"


def test_low_intensity_persona_does_not_take_a_loud_mark() -> None:
    text = decorate_reply(
        "听到了。🤣",
        mbti_type="INTJ",
        emotion="joy",
        action="respond",
        user_text="今天有件好玩的事",
        rng=_Always(),
    )
    assert "🤣" not in text
    assert "😂" not in text
    assert text.startswith("听到了。")


def test_previous_mark_is_not_repeated() -> None:
    first = decorate_reply(
        "来了。",
        mbti_type="ENFP",
        emotion="joy",
        action="respond",
        user_text="在吗",
        rng=_Always(),
    )
    second = decorate_reply(
        "还在。",
        mbti_type="ENFP",
        emotion="joy",
        action="respond",
        user_text="嗯",
        recent_messages=[{"sender_type": "companion", "content": first}],
        rng=_Always(),
    )
    first_marks = [mark for mark in load_expression_catalog().by_mark if mark in first]
    assert first_marks
    assert all(mark not in second for mark in first_marks)


def test_model_mark_is_replaced_by_the_catalog() -> None:
    text = decorate_reply(
        "这首我更吃层次 (￣▽￣)",
        mbti_type="ENFP",
        emotion="joy",
        action="share",
        user_text="你平时会喜欢什么样的歌",
        rng=_Always(),
    )
    assert "(￣▽￣)" not in text
    assert text.startswith("这首我更吃层次")
