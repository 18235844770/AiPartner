from app.modules.audio.domain.preset_voices import (
    LOCAL_PRESET_ID,
    cache_matches,
    default_preset,
    get_preset,
    load_preset_catalog,
    render_preset_instruction,
    resolve_stored_preset,
)


def test_catalog_keeps_fish_volcengine_and_longanhuan() -> None:
    catalog = load_preset_catalog()
    by_id = {item.id: item for item in catalog.voices}
    assert set(by_id) == {
        "fish-yutong",
        "fish-xue-zhiqian",
        "fish-deng-ziqi",
        "fish-wang-sulong",
        "volc-xiaohe-3",
        "longanhuan-3",
    }
    assert "volc-vivi-3" not in by_id
    assert catalog.default_id == "longanhuan-3"
    assert default_preset().id == "longanhuan-3"
    unset = resolve_stored_preset(None)
    removed = resolve_stored_preset("volc-vivi-3")
    assert unset is not None and unset.id == "longanhuan-3"
    assert removed is not None and removed.id == "longanhuan-3"
    assert resolve_stored_preset(LOCAL_PRESET_ID) is None
    assert by_id["fish-wang-sulong"].voice_id == "092d735394c64eefba2f966432c7526e"
    assert by_id["volc-xiaohe-3"].model == "doubao-seed-tts-3.0"
    assert by_id["longanhuan-3"].model == "cosyvoice-v3-plus"
    assert by_id["longanhuan-3"].voice_id == "longanhuan"
    assert get_preset("missing") is None


def test_longanhuan_instruction_uses_official_scene() -> None:
    preset = get_preset("longanhuan-3")
    assert preset is not None
    joy = render_preset_instruction(preset, "joy", "fallback")
    jealousy = render_preset_instruction(preset, "jealousy", "fallback")
    assert joy == "你正在进行闲聊对话，你说话的情感是happy。"
    assert jealousy == "你正在进行闲聊对话，你说话的情感是neutral。"


def test_cache_is_scoped_to_the_selected_preset() -> None:
    fish = "fish:61b33c9a45324f69a22dbb5f91a526d0"
    assert cache_matches(f"{fish}:s2.1-pro-free", fish)
    assert not cache_matches("Fun-CosyVoice3-0.5B-2512", fish)
    assert cache_matches("Fun-CosyVoice3-0.5B-2512", None)
    assert not cache_matches(f"{fish}:s2.1-pro-free", None)
