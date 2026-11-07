import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.file_storage import FileStorageService, StorageUnavailableError


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, True])
async def test_storage_logs_use_opaque_ids_without_paths_or_provider_text(caplog, failure):
    service = object.__new__(FileStorageService)
    bucket = MagicMock()
    bucket.download.return_value = b"fixture"
    if failure:
        bucket.download.side_effect = RuntimeError("https://upstream.test/rider@example.test?token=secret")
    service._client = SimpleNamespace(storage=SimpleNamespace(from_=lambda _: bucket))
    caplog.set_level(logging.INFO)
    path = "rides/rider@example.test/Private Rider.fit"
    if failure:
        with pytest.raises(StorageUnavailableError):
            await service.download_ride_file(path)
    else:
        await service.download_ride_file(path)
    assert "rider@example.test" not in caplog.text
    assert "Private Rider" not in caplog.text
    assert "token=secret" not in caplog.text
    assert "object_id=" in caplog.text


def test_exception_logs_keep_stack_and_meaning_without_wallet_or_email(caplog):
    from app.services.privacy_logging import scrub_log_text
    logger = logging.getLogger("privacy-log-test")
    wallet = "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgEUx"
    try:
        raise RuntimeError(f'duplicate key violates unique constraint "vault_stakes_pkey" wallet={wallet} rider@example.test')
    except RuntimeError as exc:
        logger.error("Projection failed: %s", scrub_log_text(exc), exc_info=True)
    assert "Traceback (most recent call last)" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "vault_stakes_pkey" in caplog.text
    assert wallet not in caplog.text
    assert "rider@example.test" not in caplog.text
    assert caplog.records[-1].exc_info is not None
