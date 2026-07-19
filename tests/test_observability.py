from bot.observability import anonymize_user_id


def test_anonymize_user_id_is_stable_and_not_raw():
    first = anonymize_user_id("123456")
    second = anonymize_user_id("123456")

    assert first == second
    assert first != "123456"
    assert len(first) == 16
