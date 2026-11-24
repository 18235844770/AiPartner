import json

from app.modules.dialogue.domain.context_builder import realization_messages, realization_system_prompt
from app.modules.dialogue.domain.decision import DecisionMotivation, DecisionTopic
from app.modules.dialogue.domain.enums import DialogueAction, TopicTransition
from app.modules.dialogue.domain.speech_turn import build_turn_shape, speech_issues
from app.modules.dialogue.domain.suggestion import ModelDecisionSuggestion, SelfMotivation, UserNeed
from app.modules.persona.domain.enums import MbtiType
from app.modules.persona.domain.speech_habit import load_speech_habits
from app.modules.persona.domain.templates import load_persona_templates


def test_short_turns_stay_within_two_sentences_without_a_question() -> None:
    for text in ("嗨", "早上好啊"):
        shape = build_turn_shape("respond", text)
        assert shape.max_sentences == 1
        assert shape.max_questions == 0
        assert shape.max_chars == 24
    ack = build_turn_shape("respond", "嗯")
    assert ack.max_sentences == 1
    assert ack.max_questions == 0
    assert ack.max_chars == 8


def test_short_greeting_cannot_turn_into_a_long_metaphor() -> None:
    shape = build_turn_shape("respond", "嗨")
    issues = speech_issues("嗨，这一声让我心里松了松，像是有个话头正等着被慢慢展开呢。", shape, "嗨")
    assert any("字" in item for item in issues)


def test_decision_reason_paraphrases_are_flagged() -> None:
    shape = build_turn_shape("respond", "我不是来找方案的，就是想骂两句")
    for text in ("那就骂嘛，我在这儿，不给你塞方案。", "不是因为你说了。", "这点事我心里有数。"):
        assert speech_issues(text, shape, "我不是来找方案的，就是想骂两句")


def test_answering_a_question_does_not_add_a_follow_up() -> None:
    shape = build_turn_shape("respond", "你认不认可这句话？")
    assert shape.max_sentences == 4
    assert shape.max_questions == 0


def test_an_opened_topic_can_hold_one_content_question() -> None:
    shape = build_turn_shape("respond", "家里又来电话了，开口就是催")
    assert shape.max_questions == 1
    assert build_turn_shape("respond", "不聊这个了").max_questions == 0
    assert build_turn_shape("respond", "你别劝我去").max_questions == 0
    assert build_turn_shape("respond", "哈哈").max_questions == 0


def test_a_request_for_guidance_is_answered_without_another_question() -> None:
    shape = build_turn_shape("respond", "你是觉得我应该接吗")
    assert shape.max_sentences == 4
    assert shape.max_questions == 0
    issues = speech_issues("不是让你接，我那话没替你做决定啊。", shape, "你是觉得我应该接吗")
    assert any("该怎么做" in item for item in issues)
    answered = speech_issues("我倾向先不接。开口就是催，接了多半还是那一套。", shape, "你是觉得我应该接吗")
    assert answered == []


def test_echoing_and_decision_announcements_are_flagged() -> None:
    music = "我最近老单曲循环，歌词都快背下来了"
    shape = build_turn_shape("share", music)
    echoed = speech_issues("歌词快背下来了还舍不得切，这种感觉我懂啊。", shape, music)
    assert any("又说了一遍" in item for item in echoed)
    assert any("附和过多" in item for item in echoed)
    long_yes = speech_issues(
        "会啊，太会了。走神根本就是听歌的一部分，脑子就自己飘到别处去了。",
        build_turn_shape("share", "你听歌的时候会不会也突然走神"),
        "你听歌的时候会不会也突然走神",
    )
    assert any("附和" in item for item in long_yes)
    good = speech_issues("哈哈，被你说中的感觉还挺得意呢。", build_turn_shape("react", "哈哈，被你说中了"), "哈哈，被你说中了")
    assert good == []
    for reply, user in (
        ("好，那就先不聊了。不缠着你说。", "不聊这个了"),
        ("好，不劝。去不去是你自己的事，我不替你拿主意。", "你别劝我去"),
        ("好，那就不聊了。停在这儿也不难受呢。", "不聊出门的事了"),
        ("回来啦，我还在呢，看到你这话心里挺高兴的。", "好了，我还在"),
    ):
        issues = speech_issues(reply, build_turn_shape("respond", user), user)
        assert any("决策原因" in item for item in issues)


def test_identity_emotion_and_sleep_wording_are_checked() -> None:
    lived = speech_issues(
        "会啊，旋律熟了我会跟着哼，飘回来歌已经播到下一段了。",
        build_turn_shape("share", "你听歌的时候会不会也突然走神"),
        "你听歌的时候会不会也突然走神",
    )
    assert any("没发生的经历" in item for item in lived)
    claimed = speech_issues(
        "在想刚才那点烦啊。它还没完全散。",
        build_turn_shape("share", "那你这会儿在想什么"),
        "那你这会儿在想什么",
    )
    assert any("对方的情绪" in item for item in claimed)
    own = speech_issues(
        "这件事我自己还没放下。",
        build_turn_shape("share", "那你这会儿在想什么"),
        "那你这会儿在想什么",
        emotion_ownership="self",
    )
    assert not any("对方的情绪" in item for item in own)
    tender = speech_issues("听着就让人心疼啊。", build_turn_shape("react", "今天改稿改到眼睛发酸"), "今天改稿改到眼睛发酸")
    assert any("默认体贴" in item for item in tender)
    sleep = speech_issues("好，那就安心睡吧。", build_turn_shape("close", "今天就这样，我先睡了"), "今天就这样，我先睡了")
    assert any("一点意愿" in item for item in sleep)
    kept = speech_issues(
        "有一点舍不得，还想再聊会儿。你去睡吧。",
        build_turn_shape("close", "今天就这样，我先睡了"),
        "今天就这样，我先睡了",
    )
    assert kept == []


def test_emoji_does_not_count_toward_the_char_cap() -> None:
    shape = build_turn_shape("respond", "嗯")
    issues = speech_issues("嗯。😊", shape, "嗯")
    assert issues == []
    only_face = speech_issues("(´・ω・`)", shape, "嗯")
    assert any("只有表情" in item for item in only_face)


def test_stock_and_decision_reasons_are_flagged() -> None:
    shape = build_turn_shape("respond", "嗯")
    for text in ("这一声我接住了。", "我收到了。", "我不催你。", "我分得清。"):
        issues = speech_issues(text, shape, "嗯")
        assert issues


def test_user_word_receive_is_not_treated_as_stock() -> None:
    shape = build_turn_shape("respond", "人累的时候其实更需要被接住")
    issues = speech_issues("你说的接住了，我懂。", shape, "人累的时候其实更需要被接住")
    assert not any("接住了" in item for item in issues)
    still = speech_issues("我收到了。", shape, "人累的时候其实更需要被接住")
    assert any("我收到了" in item for item in still)


def test_realization_hides_decision_reasons_for_every_persona() -> None:
    prompt = realization_system_prompt()
    assert "决策原因" in prompt
    templates = load_persona_templates()
    for mbti in MbtiType:
        messages = realization_messages(
            _suggestion(),
            [],
            immediate_facts=[{"content": "嗨", "source": "current_message"}],
            mbti_type=mbti.value,
            archive=templates[mbti].archive.dump(),
        )
        body = json.loads(messages[1].content)
        assert "reasoning_summary" not in body["decision"]
        assert "motivation" not in body["decision"]
        assert "决策原因" in messages[0].content


def test_speech_particles_follow_persona_data() -> None:
    habits = load_speech_habits()
    assert habits["ENFP"].particles == ["啊", "呢", "嘛", "哎"]
    assert habits["INTJ"].habit == "少量"
    assert "嘛" not in habits["INTJ"].particles
    templates = load_persona_templates()
    enfp = json.loads(
        realization_messages(
            _suggestion(),
            [],
            immediate_facts=[{"content": "嗨", "source": "current_message"}],
            mbti_type="ENFP",
            archive=templates[MbtiType.ENFP].archive.dump(),
        )[1].content
    )
    intj = json.loads(
        realization_messages(
            _suggestion(),
            [],
            immediate_facts=[{"content": "嗨", "source": "current_message"}],
            mbti_type="INTJ",
            archive=templates[MbtiType.INTJ].archive.dump(),
        )[1].content
    )
    assert "啊" in enfp["speech"]["particles"]
    assert "呢" in enfp["speech"]["particles"]
    assert intj["speech"]["particles"] == ["啊", "吧"]
    assert intj["speech"]["habit"] == "少量"


def _suggestion() -> ModelDecisionSuggestion:
    return ModelDecisionSuggestion(
        should_send=True,
        primary_action=DialogueAction.RESPOND,
        motivation=DecisionMotivation(primary="回应当前内容"),
        user_need=UserNeed(summary="用户在打招呼"),
        self_motivation=SelfMotivation(
            interest="没有",
            viewpoint="先打个招呼",
            desire_to_express="说一句就停",
        ),
        topic=DecisionTopic(transition=TopicTransition.NONE),
        confidence="0.5",
        reasoning_summary="这是决策原因，不能进入正文",
    )
