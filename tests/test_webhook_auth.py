import hashlib
import hmac

from apps.api.webhook_auth import verify_signature


def test_webhook_signature_accepts_only_matching_body_and_secret() -> None:
    body = b'{"event":"message"}'
    secret = "fixture-secret"
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_signature(body, signature, secret)
    assert not verify_signature(body + b" ", signature, secret)
    assert not verify_signature(body, signature, "wrong-secret")
