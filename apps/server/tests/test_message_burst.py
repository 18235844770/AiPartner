from app.modules.dialogue.domain.message_burst import split_companion_messages


def test_short_reply_stays_one_message() -> None:
    assert split_companion_messages("今天辛苦了。") == ["今天辛苦了"]
    assert split_companion_messages("我来找你。") == ["我来找你"]


def test_question_and_exclamation_stay() -> None:
    assert split_companion_messages("你想先说哪一件？") == ["你想先说哪一件？"]
    assert split_companion_messages("去睡吧！") == ["去睡吧！"]


def test_two_sentences_drop_the_periods() -> None:
    text = "就着锅吃也挺自在的。热气要是散了就有点可惜。"
    assert split_companion_messages(text) == [
        "就着锅吃也挺自在的",
        "热气要是散了就有点可惜",
    ]


def test_a_single_sentence_keeps_its_inner_commas() -> None:
    text = "还想再跟你扯两句，可你都困成这样了，去睡吧，晚安。"
    assert split_companion_messages(text) == ["还想再跟你扯两句，可你都困成这样了，去睡吧，晚安"]


def test_trailing_mark_stays_on_the_last_message() -> None:
    text = "就着锅吃也挺自在的。热气要是散了就有点可惜。 🥰"
    pieces = split_companion_messages(text)
    assert pieces[0] == "就着锅吃也挺自在的"
    assert pieces[-1].endswith("🥰")
    assert "。" not in pieces[-1]
    assert len(pieces) == 2
