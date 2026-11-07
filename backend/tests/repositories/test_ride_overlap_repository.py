from unittest.mock import MagicMock
import pytest
from postgrest.exceptions import APIError
from app.repositories.ride_economic import RideEconomicRepository, StaleEffortCoverageError


@pytest.mark.asyncio
async def test_database_overlap_error_maps_to_recompute():
    client = MagicMock()
    client.rpc.return_value.execute.side_effect = APIError({
        'code': 'BRR08', 'message': 'stale_effort_coverage', 'details': None, 'hint': None})
    repo = RideEconomicRepository(client)
    with pytest.raises(StaleEffortCoverageError):
        await repo.freeze_plan(plan={}, steps=[])


@pytest.mark.asyncio
async def test_database_outage_is_retryable_not_overlap():
    client = MagicMock()
    client.rpc.return_value.execute.side_effect = RuntimeError('database unavailable')
    with pytest.raises(RuntimeError, match='database unavailable'):
        await RideEconomicRepository(client).freeze_plan(plan={}, steps=[])
