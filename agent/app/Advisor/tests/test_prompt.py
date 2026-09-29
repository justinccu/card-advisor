from advisor.prompt import reply_language, system_prompt_for


def test_replies_are_english_unless_the_message_is_chinese():
    assert reply_language("Which card should I get?") == "English"
    assert reply_language("¿Qué tarjeta me recomiendas?") == "English"
    assert reply_language("推薦哪張卡？").startswith("Traditional Chinese")
    assert reply_language("推薦 Chase Sapphire Preferred 嗎").startswith("Traditional Chinese")
    assert reply_language("Is the 卡 good?") == "English"  # one stray character isn't Chinese


def test_the_language_is_stated_at_the_end_of_the_system_prompt():
    assert system_prompt_for("hi").rstrip().endswith("English")
