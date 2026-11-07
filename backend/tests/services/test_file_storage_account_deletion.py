from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services.file_storage import FileStorageService, StorageUnavailableError


def _service(*, list_pages: list[object] | None = None, remove_result: object = None):
    bucket = MagicMock()
    if list_pages is not None:
        bucket.list.side_effect = list_pages
    bucket.remove.return_value = remove_result
    storage = MagicMock()
    storage.from_.return_value = bucket
    client = MagicMock()
    client.storage = storage
    service = object.__new__(FileStorageService)
    service._client = client
    service._storage_base = None
    service._storage_headers = None
    return service, bucket


@pytest.mark.asyncio
async def test_delete_requires_storage_to_confirm_the_exact_removed_path() -> None:
    path = "rides/rider/ride.fit"
    service, bucket = _service(remove_result=[{"name": path}])

    assert await service.delete_ride_file(path) is True
    bucket.remove.assert_called_once_with([path])


@pytest.mark.asyncio
async def test_delete_returns_false_for_a_valid_empty_remove_result() -> None:
    service, _ = _service(remove_result=[])

    assert await service.delete_ride_file("missing.fit") is False


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [None, {}, [{"name": "another.fit"}], ["ride.fit"]])
async def test_delete_fails_closed_for_an_unverifiable_remove_result(payload: object) -> None:
    service, _ = _service(remove_result=payload)

    with pytest.raises(StorageUnavailableError, match="confirm"):
        await service.delete_ride_file("ride.fit")


@pytest.mark.asyncio
async def test_strict_existence_paginates_beyond_the_first_hundred_objects() -> None:
    first_page = [{"name": f"ride-{index:03}.fit"} for index in range(100)]
    service, bucket = _service(
        list_pages=[first_page, [{"name": "target.fit"}]],
    )

    assert await service.file_exists_strict("rides/rider/target.fit") is True
    assert bucket.list.call_args_list[0].kwargs == {
        "path": "rides/rider",
        "options": {
            "limit": 100,
            "offset": 0,
            "sortBy": {"column": "name", "order": "asc"},
        },
    }
    assert bucket.list.call_args_list[1].kwargs["options"]["offset"] == 100


@pytest.mark.asyncio
async def test_strict_existence_proves_absence_only_after_a_short_page() -> None:
    service, bucket = _service(list_pages=[[{"name": "another.fit"}]])

    assert await service.file_exists_strict("rides/rider/target.fit") is False
    assert bucket.list.call_count == 1


@pytest.mark.asyncio
async def test_strict_existence_lists_a_slashless_path_from_the_bucket_root() -> None:
    service, bucket = _service(list_pages=[[{"name": "root.fit"}]])

    assert await service.file_exists_strict("root.fit") is True
    assert bucket.list.call_args.kwargs["path"] == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [None, {}, ["target.fit"]])
async def test_strict_existence_rejects_malformed_listing_pages(payload: object) -> None:
    service, _ = _service(list_pages=[payload])

    with pytest.raises(StorageUnavailableError, match="object list"):
        await service.file_exists_strict("target.fit")


@pytest.mark.asyncio
async def test_strict_existence_surfaces_listing_outages() -> None:
    service, bucket = _service()
    bucket.list.side_effect = RuntimeError("storage unavailable")

    with pytest.raises(StorageUnavailableError, match="confirm storage object absence"):
        await service.file_exists_strict("target.fit")
