from app.middleware.rate_limiter import _sanitize_nats_kv_key


def test_sanitize_nats_kv_key_replaces_subject_invalid_chars():
    key = (
        "ratelimit.staking.user:"
        "ecffe073-23b1-449d-88c6-52e3342aaa1f.burst.1776795971"
    )

    sanitized = _sanitize_nats_kv_key(key)

    assert sanitized == (
        "ratelimit.staking.user_"
        "ecffe073-23b1-449d-88c6-52e3342aaa1f.burst.1776795971"
    )
    assert ":" not in sanitized
