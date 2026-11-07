failed 1 minute ago in 34s







2s




1s




0s




22s




6s

Run pytest -v

============================= test session starts ==============================

platform linux -- Python 3.11.14, pytest-8.3.2, pluggy-1.6.0 -- /opt/hostedtoolcache/Python/3.11.14/x64/bin/python

cachedir: .pytest_cache

rootdir: /home/runner/work/boulder-roller/boulder-roller/backend

configfile: pytest.ini

testpaths: tests

plugins: anyio-4.12.0, asyncio-0.21.1, anchorpy-0.20.0, xprocess-0.18.1

asyncio: mode=Mode.STRICT

collecting ... collected 30 items



tests/test_analytics.py::TestFitnessMetrics::test_ctl_calculation_from_zero PASSED [  3%]

tests/test_analytics.py::TestFitnessMetrics::test_atl_responds_faster_than_ctl PASSED [  6%]

tests/test_analytics.py::TestFitnessMetrics::test_tsb_calculation PASSED [ 10%]

tests/test_analytics.py::TestFitnessMetrics::test_form_status_interpretation PASSED [ 13%]

tests/test_analytics.py::TestPowerZones::test_zone_calculation_at_200_ftp PASSED [ 16%]

tests/test_analytics.py::TestPowerZones::test_get_zone_for_power PASSED  [ 20%]

tests/test_analytics.py::TestPowerZones::test_zone_distribution PASSED   [ 23%]

tests/test_analytics.py::TestTrainingTrends::test_weekly_aggregation PASSED [ 26%]

tests/test_defi.py::test_small_reward_no_vesting PASSED                  [ 30%]

tests/test_defi.py::test_large_reward_creates_vesting PASSED             [ 33%]

tests/test_defi.py::test_linear_vesting_calculation PASSED               [ 36%]

tests/test_defi.py::test_harvest_with_no_stake PASSED                    [ 40%]

tests/test_defi.py::test_harvest_calculates_correct_rewards PASSED       [ 43%]

tests/test_defi.py::test_tiered_earning PASSED                           [ 46%]

tests/test_defi.py::test_streak_bonus PASSED                             [ 50%]

tests/test_defi.py::test_record_transaction PASSED                       [ 53%]

tests/test_routes.py::test_auth_flow FAILED                              [ 56%]

tests/test_routes.py::test_refresh_rotates_token FAILED                  [ 60%]

tests/test_routes.py::test_auth_me_returns_profile FAILED                [ 63%]

tests/test_routes.py::test_logout_revokes_refresh_token FAILED           [ 66%]

tests/test_routes.py::test_rides_proofs_and_mint_flow FAILED             [ 70%]

tests/test_routes.py::test_get_rides_returns_user_rides FAILED           [ 73%]

tests/test_routes.py::test_get_token_balances_returns_totals FAILED      [ 76%]

tests/test_routes.py::test_segments_list FAILED                          [ 80%]

tests/test_routes.py::test_segments_list_with_filters FAILED             [ 83%]

tests/test_routes.py::test_segments_nearby_wraps_list FAILED             [ 86%]

tests/test_routes.py::test_health_endpoint_ok FAILED                     [ 90%]

tests/test_routes.py::test_health_endpoint_failure FAILED                [ 93%]

tests/test_routes.py::test_cal_balance_and_mint_flow FAILED              [ 96%]

tests/test_routes.py::test_staking_claims_flow FAILED                    [100%]



=================================== FAILURES ===================================

________________________________ test_auth_flow ________________________________

  + Exception Group Traceback (most recent call last):

  |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/_utils.py", line 87, in collapse_excgroups

  |     yield

  |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py", line 190, in __call__

  |     async with anyio.create_task_group() as task_group:

  |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/_backends/_asyncio.py", line 783, in __aexit__

  |     raise BaseExceptionGroup(

  | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)

  +-+---------------- 1 ----------------

    | Traceback (most recent call last):

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/runner.py", line 341, in from_call

    |     result: TResult | None = func()

    |                              ^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/runner.py", line 242, in <lambda>

    |     lambda: runtest_hook(item=item, **kwds), when=when, reraise=reraise

    |             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_hooks.py", line 512, in __call__

    |     return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_manager.py", line 120, in _hookexec

    |     return self._inner_hookexec(hook_name, methods, kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 167, in _multicall

    |     raise exception

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/threadexception.py", line 92, in pytest_runtest_call

    |     yield from thread_exception_runtest_hook()

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/threadexception.py", line 68, in thread_exception_runtest_hook

    |     yield

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/unraisableexception.py", line 95, in pytest_runtest_call

    |     yield from unraisable_exception_runtest_hook()

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/unraisableexception.py", line 70, in unraisable_exception_runtest_hook

    |     yield

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/logging.py", line 848, in pytest_runtest_call

    |     yield from self._runtest_for(item, "call")

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/logging.py", line 831, in _runtest_for

    |     yield

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/capture.py", line 879, in pytest_runtest_call

    |     return (yield)

    |             ^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/skipping.py", line 257, in pytest_runtest_call

    |     return (yield)

    |             ^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 121, in _multicall

    |     res = hook_impl.function(*args)

    |           ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/runner.py", line 174, in pytest_runtest_call

    |     item.runtest()

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/python.py", line 1627, in runtest

    |     self.ihook.pytest_pyfunc_call(pyfuncitem=self)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_hooks.py", line 512, in __call__

    |     return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_manager.py", line 120, in _hookexec

    |     return self._inner_hookexec(hook_name, methods, kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 167, in _multicall

    |     raise exception

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 53, in run_old_style_hookwrapper

    |     return result.get_result()

    |            ^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_result.py", line 103, in get_result

    |     raise exc.with_traceback(tb)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 38, in run_old_style_hookwrapper

    |     res = yield

    |           ^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 121, in _multicall

    |     res = hook_impl.function(*args)

    |           ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/python.py", line 159, in pytest_pyfunc_call

    |     result = testfunction(**testargs)

    |              ^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/tests/test_routes.py", line 961, in test_auth_flow

    |     device_id, access_token, refresh_token = authenticate(client, repo)

    |                                              ^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/tests/test_routes.py", line 940, in authenticate

    |     nonce_res = client.post("/auth/nonce", json={"wallet": repo.wallet, "device_id": device_id})

    |                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 608, in post

    |     return super().post(

    |            ^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 1132, in post

    |     return self.request(

    |            ^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 491, in request

    |     return super().request(

    |            ^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 814, in request

    |     return self.send(request, auth=auth, follow_redirects=follow_redirects)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 901, in send

    |     response = self._send_handling_auth(

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 929, in _send_handling_auth

    |     response = self._send_handling_redirects(

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 966, in _send_handling_redirects

    |     response = self._send_single_request(request)

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 1002, in _send_single_request

    |     response = transport.handle_request(request)

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 372, in handle_request

    |     raise exc

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 369, in handle_request

    |     portal.call(self.app, scope, receive, send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py", line 326, in call

    |     return cast(T_Retval, self.start_task_soon(func, *args).result())

    |                           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py", line 456, in result

    |     return self.__get_result()

    |            ^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py", line 401, in __get_result

    |     raise self._exception

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py", line 257, in _call_func

    |     retval = await retval_or_awaitable

    |              ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/fastapi/applications.py", line 1054, in __call__

    |     await super().__call__(scope, receive, send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/applications.py", line 123, in __call__

    |     await self.middleware_stack(scope, receive, send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py", line 186, in __call__

    |     raise exc

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py", line 164, in __call__

    |     await self.app(scope, receive, _send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py", line 189, in __call__

    |     with collapse_excgroups():

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/contextlib.py", line 158, in __exit__

    |     self.gen.throw(typ, value, traceback)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/_utils.py", line 93, in collapse_excgroups

    |     raise exc

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py", line 191, in __call__

    |     response = await self.dispatch_func(request, call_next)

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/app/middleware/emergency_check.py", line 20, in dispatch

    |     controls = EmergencyControls()

    |                ^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/app/services/emergency_controls.py", line 15, in __init__

    |     self._client = client or _build_supabase_client()

    |                              ^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/app/repositories.py", line 2384, in _build_supabase_client

    |     raise RuntimeError("Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.")

    | RuntimeError: Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.

    +------------------------------------



During handling of the above exception, another exception occurred:



    def test_auth_flow() -> None:

        repo = MockRepository()

        client = _build_test_client(repo)

>       device_id, access_token, refresh_token = authenticate(client, repo)



tests/test_routes.py:961: 

_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

tests/test_routes.py:940: in authenticate

    nonce_res = client.post("/auth/nonce", json={"wallet": repo.wallet, "device_id": device_id})

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:608: in post

    return super().post(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:1132: in post

    return self.request(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:491: in request

    return super().request(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:814: in request

    return self.send(request, auth=auth, follow_redirects=follow_redirects)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:901: in send

    response = self._send_handling_auth(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:929: in _send_handling_auth

    response = self._send_handling_redirects(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:966: in _send_handling_redirects

    response = self._send_single_request(request)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:1002: in _send_single_request

    response = transport.handle_request(request)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:372: in handle_request

    raise exc

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:369: in handle_request

    portal.call(self.app, scope, receive, send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py:326: in call

    return cast(T_Retval, self.start_task_soon(func, *args).result())

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py:456: in result

    return self.__get_result()

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py:401: in __get_result

    raise self._exception

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py:257: in _call_func

    retval = await retval_or_awaitable

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/fastapi/applications.py:1054: in __call__

    await super().__call__(scope, receive, send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/applications.py:123: in __call__

    await self.middleware_stack(scope, receive, send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py:186: in __call__

    raise exc

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py:164: in __call__

    await self.app(scope, receive, _send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py:189: in __call__

    with collapse_excgroups():

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/contextlib.py:158: in __exit__

    self.gen.throw(typ, value, traceback)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/_utils.py:93: in collapse_excgroups

    raise exc

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py:191: in __call__

    response = await self.dispatch_func(request, call_next)

app/middleware/emergency_check.py:20: in dispatch

    controls = EmergencyControls()

app/services/emergency_controls.py:15: in __init__

    self._client = client or _build_supabase_client()

_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 



    @lru_cache(maxsize=1)

    def _build_supabase_client() -> Client:

        settings = load_supabase_settings()

        if not settings:

>           raise RuntimeError("Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.")

E           RuntimeError: Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.



app/repositories.py:2384: RuntimeError

__________________________ test_refresh_rotates_token __________________________

  + Exception Group Traceback (most recent call last):

  |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/_utils.py", line 87, in collapse_excgroups

  |     yield

  |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py", line 190, in __call__

  |     async with anyio.create_task_group() as task_group:

  |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/_backends/_asyncio.py", line 783, in __aexit__

  |     raise BaseExceptionGroup(

  | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)

  +-+---------------- 1 ----------------

    | Traceback (most recent call last):

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/runner.py", line 341, in from_call

    |     result: TResult | None = func()

    |                              ^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/runner.py", line 242, in <lambda>

    |     lambda: runtest_hook(item=item, **kwds), when=when, reraise=reraise

    |             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_hooks.py", line 512, in __call__

    |     return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_manager.py", line 120, in _hookexec

    |     return self._inner_hookexec(hook_name, methods, kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 167, in _multicall

    |     raise exception

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/threadexception.py", line 92, in pytest_runtest_call

    |     yield from thread_exception_runtest_hook()

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/threadexception.py", line 68, in thread_exception_runtest_hook

    |     yield

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/unraisableexception.py", line 95, in pytest_runtest_call

    |     yield from unraisable_exception_runtest_hook()

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/unraisableexception.py", line 70, in unraisable_exception_runtest_hook

    |     yield

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/logging.py", line 848, in pytest_runtest_call

    |     yield from self._runtest_for(item, "call")

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/logging.py", line 831, in _runtest_for

    |     yield

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/capture.py", line 879, in pytest_runtest_call

    |     return (yield)

    |             ^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/skipping.py", line 257, in pytest_runtest_call

    |     return (yield)

    |             ^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 121, in _multicall

    |     res = hook_impl.function(*args)

    |           ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/runner.py", line 174, in pytest_runtest_call

    |     item.runtest()

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/python.py", line 1627, in runtest

    |     self.ihook.pytest_pyfunc_call(pyfuncitem=self)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_hooks.py", line 512, in __call__

    |     return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_manager.py", line 120, in _hookexec

    |     return self._inner_hookexec(hook_name, methods, kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 167, in _multicall

    |     raise exception

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 53, in run_old_style_hookwrapper

    |     return result.get_result()

    |            ^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_result.py", line 103, in get_result

    |     raise exc.with_traceback(tb)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 38, in run_old_style_hookwrapper

    |     res = yield

    |           ^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 121, in _multicall

    |     res = hook_impl.function(*args)

    |           ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/python.py", line 159, in pytest_pyfunc_call

    |     result = testfunction(**testargs)

    |              ^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/tests/test_routes.py", line 974, in test_refresh_rotates_token

    |     device_id, access_token, refresh_token = authenticate(client, repo)

    |                                              ^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/tests/test_routes.py", line 940, in authenticate

    |     nonce_res = client.post("/auth/nonce", json={"wallet": repo.wallet, "device_id": device_id})

    |                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 608, in post

    |     return super().post(

    |            ^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 1132, in post

    |     return self.request(

    |            ^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 491, in request

    |     return super().request(

    |            ^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 814, in request

    |     return self.send(request, auth=auth, follow_redirects=follow_redirects)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 901, in send

    |     response = self._send_handling_auth(

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 929, in _send_handling_auth

    |     response = self._send_handling_redirects(

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 966, in _send_handling_redirects

    |     response = self._send_single_request(request)

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 1002, in _send_single_request

    |     response = transport.handle_request(request)

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 372, in handle_request

    |     raise exc

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 369, in handle_request

    |     portal.call(self.app, scope, receive, send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py", line 326, in call

    |     return cast(T_Retval, self.start_task_soon(func, *args).result())

    |                           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py", line 456, in result

    |     return self.__get_result()

    |            ^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py", line 401, in __get_result

    |     raise self._exception

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py", line 257, in _call_func

    |     retval = await retval_or_awaitable

    |              ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/fastapi/applications.py", line 1054, in __call__

    |     await super().__call__(scope, receive, send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/applications.py", line 123, in __call__

    |     await self.middleware_stack(scope, receive, send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py", line 186, in __call__

    |     raise exc

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py", line 164, in __call__

    |     await self.app(scope, receive, _send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py", line 189, in __call__

    |     with collapse_excgroups():

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/contextlib.py", line 158, in __exit__

    |     self.gen.throw(typ, value, traceback)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/_utils.py", line 93, in collapse_excgroups

    |     raise exc

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py", line 191, in __call__

    |     response = await self.dispatch_func(request, call_next)

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/app/middleware/emergency_check.py", line 20, in dispatch

    |     controls = EmergencyControls()

    |                ^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/app/services/emergency_controls.py", line 15, in __init__

    |     self._client = client or _build_supabase_client()

    |                              ^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/app/repositories.py", line 2384, in _build_supabase_client

    |     raise RuntimeError("Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.")

    | RuntimeError: Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.

    +------------------------------------



During handling of the above exception, another exception occurred:



    def test_refresh_rotates_token() -> None:

        repo = MockRepository()

        client = _build_test_client(repo)

>       device_id, access_token, refresh_token = authenticate(client, repo)



tests/test_routes.py:974: 

_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

tests/test_routes.py:940: in authenticate

    nonce_res = client.post("/auth/nonce", json={"wallet": repo.wallet, "device_id": device_id})

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:608: in post

    return super().post(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:1132: in post

    return self.request(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:491: in request

    return super().request(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:814: in request

    return self.send(request, auth=auth, follow_redirects=follow_redirects)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:901: in send

    response = self._send_handling_auth(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:929: in _send_handling_auth

    response = self._send_handling_redirects(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:966: in _send_handling_redirects

    response = self._send_single_request(request)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:1002: in _send_single_request

    response = transport.handle_request(request)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:372: in handle_request

    raise exc

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:369: in handle_request

    portal.call(self.app, scope, receive, send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py:326: in call

    return cast(T_Retval, self.start_task_soon(func, *args).result())

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py:456: in result

    return self.__get_result()

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py:401: in __get_result

    raise self._exception

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py:257: in _call_func

    retval = await retval_or_awaitable

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/fastapi/applications.py:1054: in __call__

    await super().__call__(scope, receive, send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/applications.py:123: in __call__

    await self.middleware_stack(scope, receive, send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py:186: in __call__

    raise exc

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py:164: in __call__

    await self.app(scope, receive, _send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py:189: in __call__

    with collapse_excgroups():

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/contextlib.py:158: in __exit__

    self.gen.throw(typ, value, traceback)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/_utils.py:93: in collapse_excgroups

    raise exc

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py:191: in __call__

    response = await self.dispatch_func(request, call_next)

app/middleware/emergency_check.py:20: in dispatch

    controls = EmergencyControls()

app/services/emergency_controls.py:15: in __init__

    self._client = client or _build_supabase_client()

_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 



    @lru_cache(maxsize=1)

    def _build_supabase_client() -> Client:

        settings = load_supabase_settings()

        if not settings:

>           raise RuntimeError("Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.")

E           RuntimeError: Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.



app/repositories.py:2384: RuntimeError

_________________________ test_auth_me_returns_profile _________________________

  + Exception Group Traceback (most recent call last):

  |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/_utils.py", line 87, in collapse_excgroups

  |     yield

  |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py", line 190, in __call__

  |     async with anyio.create_task_group() as task_group:

  |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/_backends/_asyncio.py", line 783, in __aexit__

  |     raise BaseExceptionGroup(

  | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)

  +-+---------------- 1 ----------------

    | Traceback (most recent call last):

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/runner.py", line 341, in from_call

    |     result: TResult | None = func()

    |                              ^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/runner.py", line 242, in <lambda>

    |     lambda: runtest_hook(item=item, **kwds), when=when, reraise=reraise

    |             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_hooks.py", line 512, in __call__

    |     return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_manager.py", line 120, in _hookexec

    |     return self._inner_hookexec(hook_name, methods, kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 167, in _multicall

    |     raise exception

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/threadexception.py", line 92, in pytest_runtest_call

    |     yield from thread_exception_runtest_hook()

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/threadexception.py", line 68, in thread_exception_runtest_hook

    |     yield

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/unraisableexception.py", line 95, in pytest_runtest_call

    |     yield from unraisable_exception_runtest_hook()

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/unraisableexception.py", line 70, in unraisable_exception_runtest_hook

    |     yield

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/logging.py", line 848, in pytest_runtest_call

    |     yield from self._runtest_for(item, "call")

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/logging.py", line 831, in _runtest_for

    |     yield

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/capture.py", line 879, in pytest_runtest_call

    |     return (yield)

    |             ^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/skipping.py", line 257, in pytest_runtest_call

    |     return (yield)

    |             ^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 121, in _multicall

    |     res = hook_impl.function(*args)

    |           ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/runner.py", line 174, in pytest_runtest_call

    |     item.runtest()

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/python.py", line 1627, in runtest

    |     self.ihook.pytest_pyfunc_call(pyfuncitem=self)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_hooks.py", line 512, in __call__

    |     return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_manager.py", line 120, in _hookexec

    |     return self._inner_hookexec(hook_name, methods, kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 167, in _multicall

    |     raise exception

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 53, in run_old_style_hookwrapper

    |     return result.get_result()

    |            ^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_result.py", line 103, in get_result

    |     raise exc.with_traceback(tb)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 38, in run_old_style_hookwrapper

    |     res = yield

    |           ^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 121, in _multicall

    |     res = hook_impl.function(*args)

    |           ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/python.py", line 159, in pytest_pyfunc_call

    |     result = testfunction(**testargs)

    |              ^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/tests/test_routes.py", line 989, in test_auth_me_returns_profile

    |     _device_id, access_token, _ = authenticate(client, repo)

    |                                   ^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/tests/test_routes.py", line 940, in authenticate

    |     nonce_res = client.post("/auth/nonce", json={"wallet": repo.wallet, "device_id": device_id})

    |                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 608, in post

    |     return super().post(

    |            ^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 1132, in post

    |     return self.request(

    |            ^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 491, in request

    |     return super().request(

    |            ^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 814, in request

    |     return self.send(request, auth=auth, follow_redirects=follow_redirects)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 901, in send

    |     response = self._send_handling_auth(

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 929, in _send_handling_auth

    |     response = self._send_handling_redirects(

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 966, in _send_handling_redirects

    |     response = self._send_single_request(request)

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 1002, in _send_single_request

    |     response = transport.handle_request(request)

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 372, in handle_request

    |     raise exc

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 369, in handle_request

    |     portal.call(self.app, scope, receive, send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py", line 326, in call

    |     return cast(T_Retval, self.start_task_soon(func, *args).result())

    |                           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py", line 449, in result

    |     return self.__get_result()

    |            ^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py", line 401, in __get_result

    |     raise self._exception

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py", line 257, in _call_func

    |     retval = await retval_or_awaitable

    |              ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/fastapi/applications.py", line 1054, in __call__

    |     await super().__call__(scope, receive, send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/applications.py", line 123, in __call__

    |     await self.middleware_stack(scope, receive, send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py", line 186, in __call__

    |     raise exc

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py", line 164, in __call__

    |     await self.app(scope, receive, _send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py", line 189, in __call__

    |     with collapse_excgroups():

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/contextlib.py", line 158, in __exit__

    |     self.gen.throw(typ, value, traceback)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/_utils.py", line 93, in collapse_excgroups

    |     raise exc

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py", line 191, in __call__

    |     response = await self.dispatch_func(request, call_next)

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/app/middleware/emergency_check.py", line 20, in dispatch

    |     controls = EmergencyControls()

    |                ^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/app/services/emergency_controls.py", line 15, in __init__

    |     self._client = client or _build_supabase_client()

    |                              ^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/app/repositories.py", line 2384, in _build_supabase_client

    |     raise RuntimeError("Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.")

    | RuntimeError: Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.

    +------------------------------------



During handling of the above exception, another exception occurred:



    def test_auth_me_returns_profile() -> None:

        repo = MockRepository()

        client = _build_test_client(repo)

>       _device_id, access_token, _ = authenticate(client, repo)



tests/test_routes.py:989: 

_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

tests/test_routes.py:940: in authenticate

    nonce_res = client.post("/auth/nonce", json={"wallet": repo.wallet, "device_id": device_id})

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:608: in post

    return super().post(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:1132: in post

    return self.request(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:491: in request

    return super().request(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:814: in request

    return self.send(request, auth=auth, follow_redirects=follow_redirects)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:901: in send

    response = self._send_handling_auth(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:929: in _send_handling_auth

    response = self._send_handling_redirects(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:966: in _send_handling_redirects

    response = self._send_single_request(request)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:1002: in _send_single_request

    response = transport.handle_request(request)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:372: in handle_request

    raise exc

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:369: in handle_request

    portal.call(self.app, scope, receive, send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py:326: in call

    return cast(T_Retval, self.start_task_soon(func, *args).result())

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py:449: in result

    return self.__get_result()

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py:401: in __get_result

    raise self._exception

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py:257: in _call_func

    retval = await retval_or_awaitable

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/fastapi/applications.py:1054: in __call__

    await super().__call__(scope, receive, send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/applications.py:123: in __call__

    await self.middleware_stack(scope, receive, send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py:186: in __call__

    raise exc

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py:164: in __call__

    await self.app(scope, receive, _send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py:189: in __call__

    with collapse_excgroups():

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/contextlib.py:158: in __exit__

    self.gen.throw(typ, value, traceback)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/_utils.py:93: in collapse_excgroups

    raise exc

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py:191: in __call__

    response = await self.dispatch_func(request, call_next)

app/middleware/emergency_check.py:20: in dispatch

    controls = EmergencyControls()

app/services/emergency_controls.py:15: in __init__

    self._client = client or _build_supabase_client()

_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 



    @lru_cache(maxsize=1)

    def _build_supabase_client() -> Client:

        settings = load_supabase_settings()

        if not settings:

>           raise RuntimeError("Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.")

E           RuntimeError: Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.



app/repositories.py:2384: RuntimeError

______________________ test_logout_revokes_refresh_token _______________________

  + Exception Group Traceback (most recent call last):

  |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/_utils.py", line 87, in collapse_excgroups

  |     yield

  |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py", line 190, in __call__

  |     async with anyio.create_task_group() as task_group:

  |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/_backends/_asyncio.py", line 783, in __aexit__

  |     raise BaseExceptionGroup(

  | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)

  +-+---------------- 1 ----------------

    | Traceback (most recent call last):

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/runner.py", line 341, in from_call

    |     result: TResult | None = func()

    |                              ^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/runner.py", line 242, in <lambda>

    |     lambda: runtest_hook(item=item, **kwds), when=when, reraise=reraise

    |             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_hooks.py", line 512, in __call__

    |     return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_manager.py", line 120, in _hookexec

    |     return self._inner_hookexec(hook_name, methods, kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 167, in _multicall

    |     raise exception

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/threadexception.py", line 92, in pytest_runtest_call

    |     yield from thread_exception_runtest_hook()

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/threadexception.py", line 68, in thread_exception_runtest_hook

    |     yield

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/unraisableexception.py", line 95, in pytest_runtest_call

    |     yield from unraisable_exception_runtest_hook()

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/unraisableexception.py", line 70, in unraisable_exception_runtest_hook

    |     yield

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/logging.py", line 848, in pytest_runtest_call

    |     yield from self._runtest_for(item, "call")

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/logging.py", line 831, in _runtest_for

    |     yield

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/capture.py", line 879, in pytest_runtest_call

    |     return (yield)

    |             ^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/skipping.py", line 257, in pytest_runtest_call

    |     return (yield)

    |             ^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 121, in _multicall

    |     res = hook_impl.function(*args)

    |           ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/runner.py", line 174, in pytest_runtest_call

    |     item.runtest()

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/python.py", line 1627, in runtest

    |     self.ihook.pytest_pyfunc_call(pyfuncitem=self)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_hooks.py", line 512, in __call__

    |     return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_manager.py", line 120, in _hookexec

    |     return self._inner_hookexec(hook_name, methods, kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 167, in _multicall

    |     raise exception

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 53, in run_old_style_hookwrapper

    |     return result.get_result()

    |            ^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_result.py", line 103, in get_result

    |     raise exc.with_traceback(tb)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 38, in run_old_style_hookwrapper

    |     res = yield

    |           ^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 121, in _multicall

    |     res = hook_impl.function(*args)

    |           ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/python.py", line 159, in pytest_pyfunc_call

    |     result = testfunction(**testargs)

    |              ^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/tests/test_routes.py", line 1002, in test_logout_revokes_refresh_token

    |     device_id, access_token, refresh_token = authenticate(client, repo)

    |                                              ^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/tests/test_routes.py", line 940, in authenticate

    |     nonce_res = client.post("/auth/nonce", json={"wallet": repo.wallet, "device_id": device_id})

    |                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 608, in post

    |     return super().post(

    |            ^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 1132, in post

    |     return self.request(

    |            ^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 491, in request

    |     return super().request(

    |            ^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 814, in request

    |     return self.send(request, auth=auth, follow_redirects=follow_redirects)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 901, in send

    |     response = self._send_handling_auth(

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 929, in _send_handling_auth

    |     response = self._send_handling_redirects(

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 966, in _send_handling_redirects

    |     response = self._send_single_request(request)

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 1002, in _send_single_request

    |     response = transport.handle_request(request)

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 372, in handle_request

    |     raise exc

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 369, in handle_request

    |     portal.call(self.app, scope, receive, send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py", line 326, in call

    |     return cast(T_Retval, self.start_task_soon(func, *args).result())

    |                           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py", line 449, in result

    |     return self.__get_result()

    |            ^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py", line 401, in __get_result

    |     raise self._exception

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py", line 257, in _call_func

    |     retval = await retval_or_awaitable

    |              ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/fastapi/applications.py", line 1054, in __call__

    |     await super().__call__(scope, receive, send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/applications.py", line 123, in __call__

    |     await self.middleware_stack(scope, receive, send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py", line 186, in __call__

    |     raise exc

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py", line 164, in __call__

    |     await self.app(scope, receive, _send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py", line 189, in __call__

    |     with collapse_excgroups():

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/contextlib.py", line 158, in __exit__

    |     self.gen.throw(typ, value, traceback)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/_utils.py", line 93, in collapse_excgroups

    |     raise exc

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py", line 191, in __call__

    |     response = await self.dispatch_func(request, call_next)

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/app/middleware/emergency_check.py", line 20, in dispatch

    |     controls = EmergencyControls()

    |                ^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/app/services/emergency_controls.py", line 15, in __init__

    |     self._client = client or _build_supabase_client()

    |                              ^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/app/repositories.py", line 2384, in _build_supabase_client

    |     raise RuntimeError("Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.")

    | RuntimeError: Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.

    +------------------------------------



During handling of the above exception, another exception occurred:



    def test_logout_revokes_refresh_token() -> None:

        repo = MockRepository()

        client = _build_test_client(repo)

>       device_id, access_token, refresh_token = authenticate(client, repo)



tests/test_routes.py:1002: 

_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

tests/test_routes.py:940: in authenticate

    nonce_res = client.post("/auth/nonce", json={"wallet": repo.wallet, "device_id": device_id})

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:608: in post

    return super().post(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:1132: in post

    return self.request(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:491: in request

    return super().request(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:814: in request

    return self.send(request, auth=auth, follow_redirects=follow_redirects)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:901: in send

    response = self._send_handling_auth(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:929: in _send_handling_auth

    response = self._send_handling_redirects(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:966: in _send_handling_redirects

    response = self._send_single_request(request)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:1002: in _send_single_request

    response = transport.handle_request(request)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:372: in handle_request

    raise exc

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:369: in handle_request

    portal.call(self.app, scope, receive, send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py:326: in call

    return cast(T_Retval, self.start_task_soon(func, *args).result())

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py:449: in result

    return self.__get_result()

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py:401: in __get_result

    raise self._exception

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py:257: in _call_func

    retval = await retval_or_awaitable

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/fastapi/applications.py:1054: in __call__

    await super().__call__(scope, receive, send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/applications.py:123: in __call__

    await self.middleware_stack(scope, receive, send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py:186: in __call__

    raise exc

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py:164: in __call__

    await self.app(scope, receive, _send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py:189: in __call__

    with collapse_excgroups():

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/contextlib.py:158: in __exit__

    self.gen.throw(typ, value, traceback)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/_utils.py:93: in collapse_excgroups

    raise exc

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py:191: in __call__

    response = await self.dispatch_func(request, call_next)

app/middleware/emergency_check.py:20: in dispatch

    controls = EmergencyControls()

app/services/emergency_controls.py:15: in __init__

    self._client = client or _build_supabase_client()

_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 



    @lru_cache(maxsize=1)

    def _build_supabase_client() -> Client:

        settings = load_supabase_settings()

        if not settings:

>           raise RuntimeError("Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.")

E           RuntimeError: Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.



app/repositories.py:2384: RuntimeError

_______________________ test_rides_proofs_and_mint_flow ________________________

  + Exception Group Traceback (most recent call last):

  |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/_utils.py", line 87, in collapse_excgroups

  |     yield

  |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py", line 190, in __call__

  |     async with anyio.create_task_group() as task_group:

  |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/_backends/_asyncio.py", line 783, in __aexit__

  |     raise BaseExceptionGroup(

  | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)

  +-+---------------- 1 ----------------

    | Traceback (most recent call last):

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/runner.py", line 341, in from_call

    |     result: TResult | None = func()

    |                              ^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/runner.py", line 242, in <lambda>

    |     lambda: runtest_hook(item=item, **kwds), when=when, reraise=reraise

    |             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_hooks.py", line 512, in __call__

    |     return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_manager.py", line 120, in _hookexec

    |     return self._inner_hookexec(hook_name, methods, kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 167, in _multicall

    |     raise exception

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/threadexception.py", line 92, in pytest_runtest_call

    |     yield from thread_exception_runtest_hook()

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/threadexception.py", line 68, in thread_exception_runtest_hook

    |     yield

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/unraisableexception.py", line 95, in pytest_runtest_call

    |     yield from unraisable_exception_runtest_hook()

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/unraisableexception.py", line 70, in unraisable_exception_runtest_hook

    |     yield

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/logging.py", line 848, in pytest_runtest_call

    |     yield from self._runtest_for(item, "call")

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/logging.py", line 831, in _runtest_for

    |     yield

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/capture.py", line 879, in pytest_runtest_call

    |     return (yield)

    |             ^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/skipping.py", line 257, in pytest_runtest_call

    |     return (yield)

    |             ^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 121, in _multicall

    |     res = hook_impl.function(*args)

    |           ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/runner.py", line 174, in pytest_runtest_call

    |     item.runtest()

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/python.py", line 1627, in runtest

    |     self.ihook.pytest_pyfunc_call(pyfuncitem=self)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_hooks.py", line 512, in __call__

    |     return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_manager.py", line 120, in _hookexec

    |     return self._inner_hookexec(hook_name, methods, kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 167, in _multicall

    |     raise exception

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 53, in run_old_style_hookwrapper

    |     return result.get_result()

    |            ^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_result.py", line 103, in get_result

    |     raise exc.with_traceback(tb)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 38, in run_old_style_hookwrapper

    |     res = yield

    |           ^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 121, in _multicall

    |     res = hook_impl.function(*args)

    |           ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/python.py", line 159, in pytest_pyfunc_call

    |     result = testfunction(**testargs)

    |              ^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/tests/test_routes.py", line 1027, in test_rides_proofs_and_mint_flow

    |     device_id, access_token, _ = authenticate(client, repo)

    |                                  ^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/tests/test_routes.py", line 940, in authenticate

    |     nonce_res = client.post("/auth/nonce", json={"wallet": repo.wallet, "device_id": device_id})

    |                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 608, in post

    |     return super().post(

    |            ^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 1132, in post

    |     return self.request(

    |            ^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 491, in request

    |     return super().request(

    |            ^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 814, in request

    |     return self.send(request, auth=auth, follow_redirects=follow_redirects)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 901, in send

    |     response = self._send_handling_auth(

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 929, in _send_handling_auth

    |     response = self._send_handling_redirects(

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 966, in _send_handling_redirects

    |     response = self._send_single_request(request)

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 1002, in _send_single_request

    |     response = transport.handle_request(request)

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 372, in handle_request

    |     raise exc

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 369, in handle_request

    |     portal.call(self.app, scope, receive, send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py", line 326, in call

    |     return cast(T_Retval, self.start_task_soon(func, *args).result())

    |                           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py", line 456, in result

    |     return self.__get_result()

    |            ^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py", line 401, in __get_result

    |     raise self._exception

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py", line 257, in _call_func

    |     retval = await retval_or_awaitable

    |              ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/fastapi/applications.py", line 1054, in __call__

    |     await super().__call__(scope, receive, send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/applications.py", line 123, in __call__

    |     await self.middleware_stack(scope, receive, send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py", line 186, in __call__

    |     raise exc

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py", line 164, in __call__

    |     await self.app(scope, receive, _send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py", line 189, in __call__

    |     with collapse_excgroups():

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/contextlib.py", line 158, in __exit__

    |     self.gen.throw(typ, value, traceback)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/_utils.py", line 93, in collapse_excgroups

    |     raise exc

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py", line 191, in __call__

    |     response = await self.dispatch_func(request, call_next)

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/app/middleware/emergency_check.py", line 20, in dispatch

    |     controls = EmergencyControls()

    |                ^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/app/services/emergency_controls.py", line 15, in __init__

    |     self._client = client or _build_supabase_client()

    |                              ^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/app/repositories.py", line 2384, in _build_supabase_client

    |     raise RuntimeError("Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.")

    | RuntimeError: Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.

    +------------------------------------



During handling of the above exception, another exception occurred:



    def test_rides_proofs_and_mint_flow() -> None:

        repo = MockRepository()

        repo.user_states[repo.user_id] = {

            "user_id": repo.user_id,

            "cal_balance": 10_000,

            "cal_earned_today": 0.0,

            "last_cal_mint": None,

            "total_rides": 0,

            "total_tss": 0,

            "bio_score": 1000,

        }

        client = _build_test_client(repo)

>       device_id, access_token, _ = authenticate(client, repo)



tests/test_routes.py:1027: 

_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

tests/test_routes.py:940: in authenticate

    nonce_res = client.post("/auth/nonce", json={"wallet": repo.wallet, "device_id": device_id})

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:608: in post

    return super().post(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:1132: in post

    return self.request(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:491: in request

    return super().request(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:814: in request

    return self.send(request, auth=auth, follow_redirects=follow_redirects)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:901: in send

    response = self._send_handling_auth(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:929: in _send_handling_auth

    response = self._send_handling_redirects(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:966: in _send_handling_redirects

    response = self._send_single_request(request)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:1002: in _send_single_request

    response = transport.handle_request(request)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:372: in handle_request

    raise exc

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:369: in handle_request

    portal.call(self.app, scope, receive, send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py:326: in call

    return cast(T_Retval, self.start_task_soon(func, *args).result())

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py:456: in result

    return self.__get_result()

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py:401: in __get_result

    raise self._exception

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py:257: in _call_func

    retval = await retval_or_awaitable

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/fastapi/applications.py:1054: in __call__

    await super().__call__(scope, receive, send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/applications.py:123: in __call__

    await self.middleware_stack(scope, receive, send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py:186: in __call__

    raise exc

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py:164: in __call__

    await self.app(scope, receive, _send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py:189: in __call__

    with collapse_excgroups():

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/contextlib.py:158: in __exit__

    self.gen.throw(typ, value, traceback)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/_utils.py:93: in collapse_excgroups

    raise exc

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py:191: in __call__

    response = await self.dispatch_func(request, call_next)

app/middleware/emergency_check.py:20: in dispatch

    controls = EmergencyControls()

app/services/emergency_controls.py:15: in __init__

    self._client = client or _build_supabase_client()

_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 



    @lru_cache(maxsize=1)

    def _build_supabase_client() -> Client:

        settings = load_supabase_settings()

        if not settings:

>           raise RuntimeError("Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.")

E           RuntimeError: Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.



app/repositories.py:2384: RuntimeError

______________________ test_get_rides_returns_user_rides _______________________

  + Exception Group Traceback (most recent call last):

  |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/_utils.py", line 87, in collapse_excgroups

  |     yield

  |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py", line 190, in __call__

  |     async with anyio.create_task_group() as task_group:

  |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/_backends/_asyncio.py", line 783, in __aexit__

  |     raise BaseExceptionGroup(

  | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)

  +-+---------------- 1 ----------------

    | Traceback (most recent call last):

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/runner.py", line 341, in from_call

    |     result: TResult | None = func()

    |                              ^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/runner.py", line 242, in <lambda>

    |     lambda: runtest_hook(item=item, **kwds), when=when, reraise=reraise

    |             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_hooks.py", line 512, in __call__

    |     return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_manager.py", line 120, in _hookexec

    |     return self._inner_hookexec(hook_name, methods, kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 167, in _multicall

    |     raise exception

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/threadexception.py", line 92, in pytest_runtest_call

    |     yield from thread_exception_runtest_hook()

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/threadexception.py", line 68, in thread_exception_runtest_hook

    |     yield

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/unraisableexception.py", line 95, in pytest_runtest_call

    |     yield from unraisable_exception_runtest_hook()

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/unraisableexception.py", line 70, in unraisable_exception_runtest_hook

    |     yield

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/logging.py", line 848, in pytest_runtest_call

    |     yield from self._runtest_for(item, "call")

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/logging.py", line 831, in _runtest_for

    |     yield

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/capture.py", line 879, in pytest_runtest_call

    |     return (yield)

    |             ^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/skipping.py", line 257, in pytest_runtest_call

    |     return (yield)

    |             ^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 121, in _multicall

    |     res = hook_impl.function(*args)

    |           ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/runner.py", line 174, in pytest_runtest_call

    |     item.runtest()

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/python.py", line 1627, in runtest

    |     self.ihook.pytest_pyfunc_call(pyfuncitem=self)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_hooks.py", line 512, in __call__

    |     return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_manager.py", line 120, in _hookexec

    |     return self._inner_hookexec(hook_name, methods, kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 167, in _multicall

    |     raise exception

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 53, in run_old_style_hookwrapper

    |     return result.get_result()

    |            ^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_result.py", line 103, in get_result

    |     raise exc.with_traceback(tb)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 38, in run_old_style_hookwrapper

    |     res = yield

    |           ^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 121, in _multicall

    |     res = hook_impl.function(*args)

    |           ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/python.py", line 159, in pytest_pyfunc_call

    |     result = testfunction(**testargs)

    |              ^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/tests/test_routes.py", line 1074, in test_get_rides_returns_user_rides

    |     _device_id, access_token, _ = authenticate(client, repo)

    |                                   ^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/tests/test_routes.py", line 940, in authenticate

    |     nonce_res = client.post("/auth/nonce", json={"wallet": repo.wallet, "device_id": device_id})

    |                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 608, in post

    |     return super().post(

    |            ^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 1132, in post

    |     return self.request(

    |            ^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 491, in request

    |     return super().request(

    |            ^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 814, in request

    |     return self.send(request, auth=auth, follow_redirects=follow_redirects)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 901, in send

    |     response = self._send_handling_auth(

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 929, in _send_handling_auth

    |     response = self._send_handling_redirects(

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 966, in _send_handling_redirects

    |     response = self._send_single_request(request)

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 1002, in _send_single_request

    |     response = transport.handle_request(request)

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 372, in handle_request

    |     raise exc

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 369, in handle_request

    |     portal.call(self.app, scope, receive, send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py", line 326, in call

    |     return cast(T_Retval, self.start_task_soon(func, *args).result())

    |                           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py", line 449, in result

    |     return self.__get_result()

    |            ^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py", line 401, in __get_result

    |     raise self._exception

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py", line 257, in _call_func

    |     retval = await retval_or_awaitable

    |              ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/fastapi/applications.py", line 1054, in __call__

    |     await super().__call__(scope, receive, send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/applications.py", line 123, in __call__

    |     await self.middleware_stack(scope, receive, send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py", line 186, in __call__

    |     raise exc

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py", line 164, in __call__

    |     await self.app(scope, receive, _send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py", line 189, in __call__

    |     with collapse_excgroups():

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/contextlib.py", line 158, in __exit__

    |     self.gen.throw(typ, value, traceback)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/_utils.py", line 93, in collapse_excgroups

    |     raise exc

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py", line 191, in __call__

    |     response = await self.dispatch_func(request, call_next)

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/app/middleware/emergency_check.py", line 20, in dispatch

    |     controls = EmergencyControls()

    |                ^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/app/services/emergency_controls.py", line 15, in __init__

    |     self._client = client or _build_supabase_client()

    |                              ^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/app/repositories.py", line 2384, in _build_supabase_client

    |     raise RuntimeError("Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.")

    | RuntimeError: Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.

    +------------------------------------



During handling of the above exception, another exception occurred:



    def test_get_rides_returns_user_rides() -> None:

        repo = MockRepository()

        ride_id = str(uuid4())

        repo.rides_for_user = [

            {

                "id": ride_id,

                "user_id": repo.user_id,

                "started_at": "2024-10-01T12:00:00Z",

                "kcals": 450,

                "completed_at": None,

                "segments": [],

            }

        ]

        client = _build_test_client(repo)

>       _device_id, access_token, _ = authenticate(client, repo)



tests/test_routes.py:1074: 

_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

tests/test_routes.py:940: in authenticate

    nonce_res = client.post("/auth/nonce", json={"wallet": repo.wallet, "device_id": device_id})

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:608: in post

    return super().post(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:1132: in post

    return self.request(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:491: in request

    return super().request(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:814: in request

    return self.send(request, auth=auth, follow_redirects=follow_redirects)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:901: in send

    response = self._send_handling_auth(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:929: in _send_handling_auth

    response = self._send_handling_redirects(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:966: in _send_handling_redirects

    response = self._send_single_request(request)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:1002: in _send_single_request

    response = transport.handle_request(request)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:372: in handle_request

    raise exc

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:369: in handle_request

    portal.call(self.app, scope, receive, send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py:326: in call

    return cast(T_Retval, self.start_task_soon(func, *args).result())

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py:449: in result

    return self.__get_result()

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py:401: in __get_result

    raise self._exception

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py:257: in _call_func

    retval = await retval_or_awaitable

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/fastapi/applications.py:1054: in __call__

    await super().__call__(scope, receive, send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/applications.py:123: in __call__

    await self.middleware_stack(scope, receive, send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py:186: in __call__

    raise exc

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py:164: in __call__

    await self.app(scope, receive, _send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py:189: in __call__

    with collapse_excgroups():

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/contextlib.py:158: in __exit__

    self.gen.throw(typ, value, traceback)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/_utils.py:93: in collapse_excgroups

    raise exc

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py:191: in __call__

    response = await self.dispatch_func(request, call_next)

app/middleware/emergency_check.py:20: in dispatch

    controls = EmergencyControls()

app/services/emergency_controls.py:15: in __init__

    self._client = client or _build_supabase_client()

_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 



    @lru_cache(maxsize=1)

    def _build_supabase_client() -> Client:

        settings = load_supabase_settings()

        if not settings:

>           raise RuntimeError("Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.")

E           RuntimeError: Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.



app/repositories.py:2384: RuntimeError

____________________ test_get_token_balances_returns_totals ____________________

  + Exception Group Traceback (most recent call last):

  |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/_utils.py", line 87, in collapse_excgroups

  |     yield

  |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py", line 190, in __call__

  |     async with anyio.create_task_group() as task_group:

  |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/_backends/_asyncio.py", line 783, in __aexit__

  |     raise BaseExceptionGroup(

  | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)

  +-+---------------- 1 ----------------

    | Traceback (most recent call last):

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/runner.py", line 341, in from_call

    |     result: TResult | None = func()

    |                              ^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/runner.py", line 242, in <lambda>

    |     lambda: runtest_hook(item=item, **kwds), when=when, reraise=reraise

    |             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_hooks.py", line 512, in __call__

    |     return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_manager.py", line 120, in _hookexec

    |     return self._inner_hookexec(hook_name, methods, kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 167, in _multicall

    |     raise exception

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/threadexception.py", line 92, in pytest_runtest_call

    |     yield from thread_exception_runtest_hook()

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/threadexception.py", line 68, in thread_exception_runtest_hook

    |     yield

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/unraisableexception.py", line 95, in pytest_runtest_call

    |     yield from unraisable_exception_runtest_hook()

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/unraisableexception.py", line 70, in unraisable_exception_runtest_hook

    |     yield

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/logging.py", line 848, in pytest_runtest_call

    |     yield from self._runtest_for(item, "call")

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/logging.py", line 831, in _runtest_for

    |     yield

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/capture.py", line 879, in pytest_runtest_call

    |     return (yield)

    |             ^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/skipping.py", line 257, in pytest_runtest_call

    |     return (yield)

    |             ^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 121, in _multicall

    |     res = hook_impl.function(*args)

    |           ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/runner.py", line 174, in pytest_runtest_call

    |     item.runtest()

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/python.py", line 1627, in runtest

    |     self.ihook.pytest_pyfunc_call(pyfuncitem=self)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_hooks.py", line 512, in __call__

    |     return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_manager.py", line 120, in _hookexec

    |     return self._inner_hookexec(hook_name, methods, kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 167, in _multicall

    |     raise exception

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 53, in run_old_style_hookwrapper

    |     return result.get_result()

    |            ^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_result.py", line 103, in get_result

    |     raise exc.with_traceback(tb)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 38, in run_old_style_hookwrapper

    |     res = yield

    |           ^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 121, in _multicall

    |     res = hook_impl.function(*args)

    |           ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/python.py", line 159, in pytest_pyfunc_call

    |     result = testfunction(**testargs)

    |              ^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/tests/test_routes.py", line 1087, in test_get_token_balances_returns_totals

    |     _device_id, access_token, _ = authenticate(client, repo)

    |                                   ^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/tests/test_routes.py", line 940, in authenticate

    |     nonce_res = client.post("/auth/nonce", json={"wallet": repo.wallet, "device_id": device_id})

    |                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 608, in post

    |     return super().post(

    |            ^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 1132, in post

    |     return self.request(

    |            ^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 491, in request

    |     return super().request(

    |            ^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 814, in request

    |     return self.send(request, auth=auth, follow_redirects=follow_redirects)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 901, in send

    |     response = self._send_handling_auth(

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 929, in _send_handling_auth

    |     response = self._send_handling_redirects(

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 966, in _send_handling_redirects

    |     response = self._send_single_request(request)

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 1002, in _send_single_request

    |     response = transport.handle_request(request)

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 372, in handle_request

    |     raise exc

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 369, in handle_request

    |     portal.call(self.app, scope, receive, send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py", line 326, in call

    |     return cast(T_Retval, self.start_task_soon(func, *args).result())

    |                           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py", line 449, in result

    |     return self.__get_result()

    |            ^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py", line 401, in __get_result

    |     raise self._exception

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py", line 257, in _call_func

    |     retval = await retval_or_awaitable

    |              ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/fastapi/applications.py", line 1054, in __call__

    |     await super().__call__(scope, receive, send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/applications.py", line 123, in __call__

    |     await self.middleware_stack(scope, receive, send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py", line 186, in __call__

    |     raise exc

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py", line 164, in __call__

    |     await self.app(scope, receive, _send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py", line 189, in __call__

    |     with collapse_excgroups():

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/contextlib.py", line 158, in __exit__

    |     self.gen.throw(typ, value, traceback)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/_utils.py", line 93, in collapse_excgroups

    |     raise exc

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py", line 191, in __call__

    |     response = await self.dispatch_func(request, call_next)

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/app/middleware/emergency_check.py", line 20, in dispatch

    |     controls = EmergencyControls()

    |                ^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/app/services/emergency_controls.py", line 15, in __init__

    |     self._client = client or _build_supabase_client()

    |                              ^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/app/repositories.py", line 2384, in _build_supabase_client

    |     raise RuntimeError("Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.")

    | RuntimeError: Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.

    +------------------------------------



During handling of the above exception, another exception occurred:



    def test_get_token_balances_returns_totals() -> None:

        repo = MockRepository()

        repo.token_balances = {"dung": 10.5, "kcal": 1200.0}

        client = _build_test_client(repo)

>       _device_id, access_token, _ = authenticate(client, repo)



tests/test_routes.py:1087: 

_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

tests/test_routes.py:940: in authenticate

    nonce_res = client.post("/auth/nonce", json={"wallet": repo.wallet, "device_id": device_id})

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:608: in post

    return super().post(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:1132: in post

    return self.request(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:491: in request

    return super().request(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:814: in request

    return self.send(request, auth=auth, follow_redirects=follow_redirects)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:901: in send

    response = self._send_handling_auth(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:929: in _send_handling_auth

    response = self._send_handling_redirects(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:966: in _send_handling_redirects

    response = self._send_single_request(request)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:1002: in _send_single_request

    response = transport.handle_request(request)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:372: in handle_request

    raise exc

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:369: in handle_request

    portal.call(self.app, scope, receive, send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py:326: in call

    return cast(T_Retval, self.start_task_soon(func, *args).result())

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py:449: in result

    return self.__get_result()

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py:401: in __get_result

    raise self._exception

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py:257: in _call_func

    retval = await retval_or_awaitable

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/fastapi/applications.py:1054: in __call__

    await super().__call__(scope, receive, send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/applications.py:123: in __call__

    await self.middleware_stack(scope, receive, send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py:186: in __call__

    raise exc

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py:164: in __call__

    await self.app(scope, receive, _send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py:189: in __call__

    with collapse_excgroups():

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/contextlib.py:158: in __exit__

    self.gen.throw(typ, value, traceback)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/_utils.py:93: in collapse_excgroups

    raise exc

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py:191: in __call__

    response = await self.dispatch_func(request, call_next)

app/middleware/emergency_check.py:20: in dispatch

    controls = EmergencyControls()

app/services/emergency_controls.py:15: in __init__

    self._client = client or _build_supabase_client()

_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 



    @lru_cache(maxsize=1)

    def _build_supabase_client() -> Client:

        settings = load_supabase_settings()

        if not settings:

>           raise RuntimeError("Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.")

E           RuntimeError: Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.



app/repositories.py:2384: RuntimeError

______________________________ test_segments_list ______________________________

  + Exception Group Traceback (most recent call last):

  |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/_utils.py", line 87, in collapse_excgroups

  |     yield

  |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py", line 190, in __call__

  |     async with anyio.create_task_group() as task_group:

  |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/_backends/_asyncio.py", line 783, in __aexit__

  |     raise BaseExceptionGroup(

  | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)

  +-+---------------- 1 ----------------

    | Traceback (most recent call last):

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/runner.py", line 341, in from_call

    |     result: TResult | None = func()

    |                              ^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/runner.py", line 242, in <lambda>

    |     lambda: runtest_hook(item=item, **kwds), when=when, reraise=reraise

    |             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_hooks.py", line 512, in __call__

    |     return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_manager.py", line 120, in _hookexec

    |     return self._inner_hookexec(hook_name, methods, kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 167, in _multicall

    |     raise exception

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/threadexception.py", line 92, in pytest_runtest_call

    |     yield from thread_exception_runtest_hook()

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/threadexception.py", line 68, in thread_exception_runtest_hook

    |     yield

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/unraisableexception.py", line 95, in pytest_runtest_call

    |     yield from unraisable_exception_runtest_hook()

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/unraisableexception.py", line 70, in unraisable_exception_runtest_hook

    |     yield

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/logging.py", line 848, in pytest_runtest_call

    |     yield from self._runtest_for(item, "call")

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/logging.py", line 831, in _runtest_for

    |     yield

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/capture.py", line 879, in pytest_runtest_call

    |     return (yield)

    |             ^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/skipping.py", line 257, in pytest_runtest_call

    |     return (yield)

    |             ^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 121, in _multicall

    |     res = hook_impl.function(*args)

    |           ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/runner.py", line 174, in pytest_runtest_call

    |     item.runtest()

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/python.py", line 1627, in runtest

    |     self.ihook.pytest_pyfunc_call(pyfuncitem=self)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_hooks.py", line 512, in __call__

    |     return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_manager.py", line 120, in _hookexec

    |     return self._inner_hookexec(hook_name, methods, kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 167, in _multicall

    |     raise exception

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 53, in run_old_style_hookwrapper

    |     return result.get_result()

    |            ^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_result.py", line 103, in get_result

    |     raise exc.with_traceback(tb)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 38, in run_old_style_hookwrapper

    |     res = yield

    |           ^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 121, in _multicall

    |     res = hook_impl.function(*args)

    |           ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/python.py", line 159, in pytest_pyfunc_call

    |     result = testfunction(**testargs)

    |              ^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/tests/test_routes.py", line 1097, in test_segments_list

    |     response = client.get("/segments/list")

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 523, in get

    |     return super().get(

    |            ^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 1041, in get

    |     return self.request(

    |            ^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 491, in request

    |     return super().request(

    |            ^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 814, in request

    |     return self.send(request, auth=auth, follow_redirects=follow_redirects)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 901, in send

    |     response = self._send_handling_auth(

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 929, in _send_handling_auth

    |     response = self._send_handling_redirects(

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 966, in _send_handling_redirects

    |     response = self._send_single_request(request)

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 1002, in _send_single_request

    |     response = transport.handle_request(request)

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 372, in handle_request

    |     raise exc

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 369, in handle_request

    |     portal.call(self.app, scope, receive, send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py", line 326, in call

    |     return cast(T_Retval, self.start_task_soon(func, *args).result())

    |                           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py", line 456, in result

    |     return self.__get_result()

    |            ^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py", line 401, in __get_result

    |     raise self._exception

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py", line 257, in _call_func

    |     retval = await retval_or_awaitable

    |              ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/fastapi/applications.py", line 1054, in __call__

    |     await super().__call__(scope, receive, send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/applications.py", line 123, in __call__

    |     await self.middleware_stack(scope, receive, send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py", line 186, in __call__

    |     raise exc

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py", line 164, in __call__

    |     await self.app(scope, receive, _send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py", line 189, in __call__

    |     with collapse_excgroups():

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/contextlib.py", line 158, in __exit__

    |     self.gen.throw(typ, value, traceback)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/_utils.py", line 93, in collapse_excgroups

    |     raise exc

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py", line 191, in __call__

    |     response = await self.dispatch_func(request, call_next)

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/app/middleware/emergency_check.py", line 20, in dispatch

    |     controls = EmergencyControls()

    |                ^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/app/services/emergency_controls.py", line 15, in __init__

    |     self._client = client or _build_supabase_client()

    |                              ^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/app/repositories.py", line 2384, in _build_supabase_client

    |     raise RuntimeError("Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.")

    | RuntimeError: Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.

    +------------------------------------



During handling of the above exception, another exception occurred:



    def test_segments_list() -> None:

        repo = MockRepository()

        client = _build_test_client(repo)

    

>       response = client.get("/segments/list")



tests/test_routes.py:1097: 

_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:523: in get

    return super().get(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:1041: in get

    return self.request(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:491: in request

    return super().request(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:814: in request

    return self.send(request, auth=auth, follow_redirects=follow_redirects)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:901: in send

    response = self._send_handling_auth(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:929: in _send_handling_auth

    response = self._send_handling_redirects(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:966: in _send_handling_redirects

    response = self._send_single_request(request)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:1002: in _send_single_request

    response = transport.handle_request(request)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:372: in handle_request

    raise exc

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:369: in handle_request

    portal.call(self.app, scope, receive, send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py:326: in call

    return cast(T_Retval, self.start_task_soon(func, *args).result())

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py:456: in result

    return self.__get_result()

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py:401: in __get_result

    raise self._exception

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py:257: in _call_func

    retval = await retval_or_awaitable

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/fastapi/applications.py:1054: in __call__

    await super().__call__(scope, receive, send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/applications.py:123: in __call__

    await self.middleware_stack(scope, receive, send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py:186: in __call__

    raise exc

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py:164: in __call__

    await self.app(scope, receive, _send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py:189: in __call__

    with collapse_excgroups():

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/contextlib.py:158: in __exit__

    self.gen.throw(typ, value, traceback)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/_utils.py:93: in collapse_excgroups

    raise exc

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py:191: in __call__

    response = await self.dispatch_func(request, call_next)

app/middleware/emergency_check.py:20: in dispatch

    controls = EmergencyControls()

app/services/emergency_controls.py:15: in __init__

    self._client = client or _build_supabase_client()

_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 



    @lru_cache(maxsize=1)

    def _build_supabase_client() -> Client:

        settings = load_supabase_settings()

        if not settings:

>           raise RuntimeError("Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.")

E           RuntimeError: Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.



app/repositories.py:2384: RuntimeError

_______________________ test_segments_list_with_filters ________________________

  + Exception Group Traceback (most recent call last):

  |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/_utils.py", line 87, in collapse_excgroups

  |     yield

  |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py", line 190, in __call__

  |     async with anyio.create_task_group() as task_group:

  |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/_backends/_asyncio.py", line 783, in __aexit__

  |     raise BaseExceptionGroup(

  | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)

  +-+---------------- 1 ----------------

    | Traceback (most recent call last):

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/runner.py", line 341, in from_call

    |     result: TResult | None = func()

    |                              ^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/runner.py", line 242, in <lambda>

    |     lambda: runtest_hook(item=item, **kwds), when=when, reraise=reraise

    |             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_hooks.py", line 512, in __call__

    |     return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_manager.py", line 120, in _hookexec

    |     return self._inner_hookexec(hook_name, methods, kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 167, in _multicall

    |     raise exception

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/threadexception.py", line 92, in pytest_runtest_call

    |     yield from thread_exception_runtest_hook()

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/threadexception.py", line 68, in thread_exception_runtest_hook

    |     yield

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/unraisableexception.py", line 95, in pytest_runtest_call

    |     yield from unraisable_exception_runtest_hook()

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/unraisableexception.py", line 70, in unraisable_exception_runtest_hook

    |     yield

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/logging.py", line 848, in pytest_runtest_call

    |     yield from self._runtest_for(item, "call")

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/logging.py", line 831, in _runtest_for

    |     yield

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/capture.py", line 879, in pytest_runtest_call

    |     return (yield)

    |             ^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/skipping.py", line 257, in pytest_runtest_call

    |     return (yield)

    |             ^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 121, in _multicall

    |     res = hook_impl.function(*args)

    |           ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/runner.py", line 174, in pytest_runtest_call

    |     item.runtest()

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/python.py", line 1627, in runtest

    |     self.ihook.pytest_pyfunc_call(pyfuncitem=self)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_hooks.py", line 512, in __call__

    |     return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_manager.py", line 120, in _hookexec

    |     return self._inner_hookexec(hook_name, methods, kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 167, in _multicall

    |     raise exception

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 53, in run_old_style_hookwrapper

    |     return result.get_result()

    |            ^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_result.py", line 103, in get_result

    |     raise exc.with_traceback(tb)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 38, in run_old_style_hookwrapper

    |     res = yield

    |           ^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 121, in _multicall

    |     res = hook_impl.function(*args)

    |           ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/python.py", line 159, in pytest_pyfunc_call

    |     result = testfunction(**testargs)

    |              ^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/tests/test_routes.py", line 1109, in test_segments_list_with_filters

    |     response = client.get("/segments/list", params={"q": "Test", "bbox": "-105,39,-104,40"})

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 523, in get

    |     return super().get(

    |            ^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 1041, in get

    |     return self.request(

    |            ^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 491, in request

    |     return super().request(

    |            ^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 814, in request

    |     return self.send(request, auth=auth, follow_redirects=follow_redirects)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 901, in send

    |     response = self._send_handling_auth(

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 929, in _send_handling_auth

    |     response = self._send_handling_redirects(

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 966, in _send_handling_redirects

    |     response = self._send_single_request(request)

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 1002, in _send_single_request

    |     response = transport.handle_request(request)

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 372, in handle_request

    |     raise exc

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 369, in handle_request

    |     portal.call(self.app, scope, receive, send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py", line 326, in call

    |     return cast(T_Retval, self.start_task_soon(func, *args).result())

    |                           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py", line 449, in result

    |     return self.__get_result()

    |            ^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py", line 401, in __get_result

    |     raise self._exception

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py", line 257, in _call_func

    |     retval = await retval_or_awaitable

    |              ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/fastapi/applications.py", line 1054, in __call__

    |     await super().__call__(scope, receive, send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/applications.py", line 123, in __call__

    |     await self.middleware_stack(scope, receive, send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py", line 186, in __call__

    |     raise exc

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py", line 164, in __call__

    |     await self.app(scope, receive, _send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py", line 189, in __call__

    |     with collapse_excgroups():

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/contextlib.py", line 158, in __exit__

    |     self.gen.throw(typ, value, traceback)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/_utils.py", line 93, in collapse_excgroups

    |     raise exc

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py", line 191, in __call__

    |     response = await self.dispatch_func(request, call_next)

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/app/middleware/emergency_check.py", line 20, in dispatch

    |     controls = EmergencyControls()

    |                ^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/app/services/emergency_controls.py", line 15, in __init__

    |     self._client = client or _build_supabase_client()

    |                              ^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/app/repositories.py", line 2384, in _build_supabase_client

    |     raise RuntimeError("Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.")

    | RuntimeError: Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.

    +------------------------------------



During handling of the above exception, another exception occurred:



    def test_segments_list_with_filters() -> None:

        repo = MockRepository()

        client = _build_test_client(repo)

    

>       response = client.get("/segments/list", params={"q": "Test", "bbox": "-105,39,-104,40"})



tests/test_routes.py:1109: 

_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:523: in get

    return super().get(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:1041: in get

    return self.request(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:491: in request

    return super().request(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:814: in request

    return self.send(request, auth=auth, follow_redirects=follow_redirects)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:901: in send

    response = self._send_handling_auth(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:929: in _send_handling_auth

    response = self._send_handling_redirects(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:966: in _send_handling_redirects

    response = self._send_single_request(request)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:1002: in _send_single_request

    response = transport.handle_request(request)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:372: in handle_request

    raise exc

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:369: in handle_request

    portal.call(self.app, scope, receive, send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py:326: in call

    return cast(T_Retval, self.start_task_soon(func, *args).result())

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py:449: in result

    return self.__get_result()

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py:401: in __get_result

    raise self._exception

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py:257: in _call_func

    retval = await retval_or_awaitable

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/fastapi/applications.py:1054: in __call__

    await super().__call__(scope, receive, send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/applications.py:123: in __call__

    await self.middleware_stack(scope, receive, send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py:186: in __call__

    raise exc

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py:164: in __call__

    await self.app(scope, receive, _send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py:189: in __call__

    with collapse_excgroups():

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/contextlib.py:158: in __exit__

    self.gen.throw(typ, value, traceback)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/_utils.py:93: in collapse_excgroups

    raise exc

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py:191: in __call__

    response = await self.dispatch_func(request, call_next)

app/middleware/emergency_check.py:20: in dispatch

    controls = EmergencyControls()

app/services/emergency_controls.py:15: in __init__

    self._client = client or _build_supabase_client()

_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 



    @lru_cache(maxsize=1)

    def _build_supabase_client() -> Client:

        settings = load_supabase_settings()

        if not settings:

>           raise RuntimeError("Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.")

E           RuntimeError: Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.



app/repositories.py:2384: RuntimeError

_______________________ test_segments_nearby_wraps_list ________________________

  + Exception Group Traceback (most recent call last):

  |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/_utils.py", line 87, in collapse_excgroups

  |     yield

  |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py", line 190, in __call__

  |     async with anyio.create_task_group() as task_group:

  |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/_backends/_asyncio.py", line 783, in __aexit__

  |     raise BaseExceptionGroup(

  | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)

  +-+---------------- 1 ----------------

    | Traceback (most recent call last):

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/runner.py", line 341, in from_call

    |     result: TResult | None = func()

    |                              ^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/runner.py", line 242, in <lambda>

    |     lambda: runtest_hook(item=item, **kwds), when=when, reraise=reraise

    |             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_hooks.py", line 512, in __call__

    |     return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_manager.py", line 120, in _hookexec

    |     return self._inner_hookexec(hook_name, methods, kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 167, in _multicall

    |     raise exception

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/threadexception.py", line 92, in pytest_runtest_call

    |     yield from thread_exception_runtest_hook()

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/threadexception.py", line 68, in thread_exception_runtest_hook

    |     yield

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/unraisableexception.py", line 95, in pytest_runtest_call

    |     yield from unraisable_exception_runtest_hook()

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/unraisableexception.py", line 70, in unraisable_exception_runtest_hook

    |     yield

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/logging.py", line 848, in pytest_runtest_call

    |     yield from self._runtest_for(item, "call")

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/logging.py", line 831, in _runtest_for

    |     yield

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/capture.py", line 879, in pytest_runtest_call

    |     return (yield)

    |             ^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/skipping.py", line 257, in pytest_runtest_call

    |     return (yield)

    |             ^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 121, in _multicall

    |     res = hook_impl.function(*args)

    |           ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/runner.py", line 174, in pytest_runtest_call

    |     item.runtest()

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/python.py", line 1627, in runtest

    |     self.ihook.pytest_pyfunc_call(pyfuncitem=self)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_hooks.py", line 512, in __call__

    |     return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_manager.py", line 120, in _hookexec

    |     return self._inner_hookexec(hook_name, methods, kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 167, in _multicall

    |     raise exception

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 53, in run_old_style_hookwrapper

    |     return result.get_result()

    |            ^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_result.py", line 103, in get_result

    |     raise exc.with_traceback(tb)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 38, in run_old_style_hookwrapper

    |     res = yield

    |           ^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 121, in _multicall

    |     res = hook_impl.function(*args)

    |           ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/python.py", line 159, in pytest_pyfunc_call

    |     result = testfunction(**testargs)

    |              ^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/tests/test_routes.py", line 1119, in test_segments_nearby_wraps_list

    |     response = client.get("/segments/nearby", params={"lat": 40.0, "lon": -105.0, "radius_km": 10})

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 523, in get

    |     return super().get(

    |            ^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 1041, in get

    |     return self.request(

    |            ^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 491, in request

    |     return super().request(

    |            ^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 814, in request

    |     return self.send(request, auth=auth, follow_redirects=follow_redirects)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 901, in send

    |     response = self._send_handling_auth(

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 929, in _send_handling_auth

    |     response = self._send_handling_redirects(

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 966, in _send_handling_redirects

    |     response = self._send_single_request(request)

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 1002, in _send_single_request

    |     response = transport.handle_request(request)

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 372, in handle_request

    |     raise exc

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 369, in handle_request

    |     portal.call(self.app, scope, receive, send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py", line 326, in call

    |     return cast(T_Retval, self.start_task_soon(func, *args).result())

    |                           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py", line 449, in result

    |     return self.__get_result()

    |            ^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py", line 401, in __get_result

    |     raise self._exception

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py", line 257, in _call_func

    |     retval = await retval_or_awaitable

    |              ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/fastapi/applications.py", line 1054, in __call__

    |     await super().__call__(scope, receive, send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/applications.py", line 123, in __call__

    |     await self.middleware_stack(scope, receive, send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py", line 186, in __call__

    |     raise exc

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py", line 164, in __call__

    |     await self.app(scope, receive, _send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py", line 189, in __call__

    |     with collapse_excgroups():

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/contextlib.py", line 158, in __exit__

    |     self.gen.throw(typ, value, traceback)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/_utils.py", line 93, in collapse_excgroups

    |     raise exc

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py", line 191, in __call__

    |     response = await self.dispatch_func(request, call_next)

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/app/middleware/emergency_check.py", line 20, in dispatch

    |     controls = EmergencyControls()

    |                ^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/app/services/emergency_controls.py", line 15, in __init__

    |     self._client = client or _build_supabase_client()

    |                              ^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/app/repositories.py", line 2384, in _build_supabase_client

    |     raise RuntimeError("Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.")

    | RuntimeError: Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.

    +------------------------------------



During handling of the above exception, another exception occurred:



    def test_segments_nearby_wraps_list() -> None:

        repo = MockRepository()

        client = _build_test_client(repo)

    

>       response = client.get("/segments/nearby", params={"lat": 40.0, "lon": -105.0, "radius_km": 10})



tests/test_routes.py:1119: 

_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:523: in get

    return super().get(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:1041: in get

    return self.request(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:491: in request

    return super().request(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:814: in request

    return self.send(request, auth=auth, follow_redirects=follow_redirects)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:901: in send

    response = self._send_handling_auth(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:929: in _send_handling_auth

    response = self._send_handling_redirects(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:966: in _send_handling_redirects

    response = self._send_single_request(request)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:1002: in _send_single_request

    response = transport.handle_request(request)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:372: in handle_request

    raise exc

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:369: in handle_request

    portal.call(self.app, scope, receive, send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py:326: in call

    return cast(T_Retval, self.start_task_soon(func, *args).result())

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py:449: in result

    return self.__get_result()

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py:401: in __get_result

    raise self._exception

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py:257: in _call_func

    retval = await retval_or_awaitable

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/fastapi/applications.py:1054: in __call__

    await super().__call__(scope, receive, send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/applications.py:123: in __call__

    await self.middleware_stack(scope, receive, send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py:186: in __call__

    raise exc

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py:164: in __call__

    await self.app(scope, receive, _send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py:189: in __call__

    with collapse_excgroups():

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/contextlib.py:158: in __exit__

    self.gen.throw(typ, value, traceback)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/_utils.py:93: in collapse_excgroups

    raise exc

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py:191: in __call__

    response = await self.dispatch_func(request, call_next)

app/middleware/emergency_check.py:20: in dispatch

    controls = EmergencyControls()

app/services/emergency_controls.py:15: in __init__

    self._client = client or _build_supabase_client()

_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 



    @lru_cache(maxsize=1)

    def _build_supabase_client() -> Client:

        settings = load_supabase_settings()

        if not settings:

>           raise RuntimeError("Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.")

E           RuntimeError: Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.



app/repositories.py:2384: RuntimeError

___________________________ test_health_endpoint_ok ____________________________

  + Exception Group Traceback (most recent call last):

  |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/_utils.py", line 87, in collapse_excgroups

  |     yield

  |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py", line 190, in __call__

  |     async with anyio.create_task_group() as task_group:

  |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/_backends/_asyncio.py", line 783, in __aexit__

  |     raise BaseExceptionGroup(

  | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)

  +-+---------------- 1 ----------------

    | Traceback (most recent call last):

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/runner.py", line 341, in from_call

    |     result: TResult | None = func()

    |                              ^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/runner.py", line 242, in <lambda>

    |     lambda: runtest_hook(item=item, **kwds), when=when, reraise=reraise

    |             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_hooks.py", line 512, in __call__

    |     return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_manager.py", line 120, in _hookexec

    |     return self._inner_hookexec(hook_name, methods, kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 167, in _multicall

    |     raise exception

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/threadexception.py", line 92, in pytest_runtest_call

    |     yield from thread_exception_runtest_hook()

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/threadexception.py", line 68, in thread_exception_runtest_hook

    |     yield

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/unraisableexception.py", line 95, in pytest_runtest_call

    |     yield from unraisable_exception_runtest_hook()

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/unraisableexception.py", line 70, in unraisable_exception_runtest_hook

    |     yield

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/logging.py", line 848, in pytest_runtest_call

    |     yield from self._runtest_for(item, "call")

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/logging.py", line 831, in _runtest_for

    |     yield

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/capture.py", line 879, in pytest_runtest_call

    |     return (yield)

    |             ^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/skipping.py", line 257, in pytest_runtest_call

    |     return (yield)

    |             ^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 121, in _multicall

    |     res = hook_impl.function(*args)

    |           ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/runner.py", line 174, in pytest_runtest_call

    |     item.runtest()

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/python.py", line 1627, in runtest

    |     self.ihook.pytest_pyfunc_call(pyfuncitem=self)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_hooks.py", line 512, in __call__

    |     return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_manager.py", line 120, in _hookexec

    |     return self._inner_hookexec(hook_name, methods, kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 167, in _multicall

    |     raise exception

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 53, in run_old_style_hookwrapper

    |     return result.get_result()

    |            ^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_result.py", line 103, in get_result

    |     raise exc.with_traceback(tb)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 38, in run_old_style_hookwrapper

    |     res = yield

    |           ^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 121, in _multicall

    |     res = hook_impl.function(*args)

    |           ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/python.py", line 159, in pytest_pyfunc_call

    |     result = testfunction(**testargs)

    |              ^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/tests/test_routes.py", line 1134, in test_health_endpoint_ok

    |     response = client.get("/health/db")

    |                ^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 523, in get

    |     return super().get(

    |            ^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 1041, in get

    |     return self.request(

    |            ^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 491, in request

    |     return super().request(

    |            ^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 814, in request

    |     return self.send(request, auth=auth, follow_redirects=follow_redirects)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 901, in send

    |     response = self._send_handling_auth(

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 929, in _send_handling_auth

    |     response = self._send_handling_redirects(

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 966, in _send_handling_redirects

    |     response = self._send_single_request(request)

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 1002, in _send_single_request

    |     response = transport.handle_request(request)

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 372, in handle_request

    |     raise exc

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 369, in handle_request

    |     portal.call(self.app, scope, receive, send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py", line 326, in call

    |     return cast(T_Retval, self.start_task_soon(func, *args).result())

    |                           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py", line 456, in result

    |     return self.__get_result()

    |            ^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py", line 401, in __get_result

    |     raise self._exception

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py", line 257, in _call_func

    |     retval = await retval_or_awaitable

    |              ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/fastapi/applications.py", line 1054, in __call__

    |     await super().__call__(scope, receive, send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/applications.py", line 123, in __call__

    |     await self.middleware_stack(scope, receive, send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py", line 186, in __call__

    |     raise exc

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py", line 164, in __call__

    |     await self.app(scope, receive, _send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py", line 189, in __call__

    |     with collapse_excgroups():

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/contextlib.py", line 158, in __exit__

    |     self.gen.throw(typ, value, traceback)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/_utils.py", line 93, in collapse_excgroups

    |     raise exc

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py", line 191, in __call__

    |     response = await self.dispatch_func(request, call_next)

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/app/middleware/emergency_check.py", line 20, in dispatch

    |     controls = EmergencyControls()

    |                ^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/app/services/emergency_controls.py", line 15, in __init__

    |     self._client = client or _build_supabase_client()

    |                              ^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/app/repositories.py", line 2384, in _build_supabase_client

    |     raise RuntimeError("Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.")

    | RuntimeError: Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.

    +------------------------------------



During handling of the above exception, another exception occurred:



    def test_health_endpoint_ok() -> None:

        repo = MockRepository()

        repo.health_ok = True

        client = _build_test_client(repo)

    

>       response = client.get("/health/db")



tests/test_routes.py:1134: 

_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:523: in get

    return super().get(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:1041: in get

    return self.request(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:491: in request

    return super().request(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:814: in request

    return self.send(request, auth=auth, follow_redirects=follow_redirects)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:901: in send

    response = self._send_handling_auth(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:929: in _send_handling_auth

    response = self._send_handling_redirects(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:966: in _send_handling_redirects

    response = self._send_single_request(request)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:1002: in _send_single_request

    response = transport.handle_request(request)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:372: in handle_request

    raise exc

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:369: in handle_request

    portal.call(self.app, scope, receive, send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py:326: in call

    return cast(T_Retval, self.start_task_soon(func, *args).result())

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py:456: in result

    return self.__get_result()

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py:401: in __get_result

    raise self._exception

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py:257: in _call_func

    retval = await retval_or_awaitable

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/fastapi/applications.py:1054: in __call__

    await super().__call__(scope, receive, send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/applications.py:123: in __call__

    await self.middleware_stack(scope, receive, send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py:186: in __call__

    raise exc

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py:164: in __call__

    await self.app(scope, receive, _send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py:189: in __call__

    with collapse_excgroups():

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/contextlib.py:158: in __exit__

    self.gen.throw(typ, value, traceback)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/_utils.py:93: in collapse_excgroups

    raise exc

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py:191: in __call__

    response = await self.dispatch_func(request, call_next)

app/middleware/emergency_check.py:20: in dispatch

    controls = EmergencyControls()

app/services/emergency_controls.py:15: in __init__

    self._client = client or _build_supabase_client()

_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 



    @lru_cache(maxsize=1)

    def _build_supabase_client() -> Client:

        settings = load_supabase_settings()

        if not settings:

>           raise RuntimeError("Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.")

E           RuntimeError: Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.



app/repositories.py:2384: RuntimeError

_________________________ test_health_endpoint_failure _________________________

  + Exception Group Traceback (most recent call last):

  |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/_utils.py", line 87, in collapse_excgroups

  |     yield

  |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py", line 190, in __call__

  |     async with anyio.create_task_group() as task_group:

  |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/_backends/_asyncio.py", line 783, in __aexit__

  |     raise BaseExceptionGroup(

  | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)

  +-+---------------- 1 ----------------

    | Traceback (most recent call last):

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/runner.py", line 341, in from_call

    |     result: TResult | None = func()

    |                              ^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/runner.py", line 242, in <lambda>

    |     lambda: runtest_hook(item=item, **kwds), when=when, reraise=reraise

    |             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_hooks.py", line 512, in __call__

    |     return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_manager.py", line 120, in _hookexec

    |     return self._inner_hookexec(hook_name, methods, kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 167, in _multicall

    |     raise exception

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/threadexception.py", line 92, in pytest_runtest_call

    |     yield from thread_exception_runtest_hook()

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/threadexception.py", line 68, in thread_exception_runtest_hook

    |     yield

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/unraisableexception.py", line 95, in pytest_runtest_call

    |     yield from unraisable_exception_runtest_hook()

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/unraisableexception.py", line 70, in unraisable_exception_runtest_hook

    |     yield

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/logging.py", line 848, in pytest_runtest_call

    |     yield from self._runtest_for(item, "call")

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/logging.py", line 831, in _runtest_for

    |     yield

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/capture.py", line 879, in pytest_runtest_call

    |     return (yield)

    |             ^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/skipping.py", line 257, in pytest_runtest_call

    |     return (yield)

    |             ^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 121, in _multicall

    |     res = hook_impl.function(*args)

    |           ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/runner.py", line 174, in pytest_runtest_call

    |     item.runtest()

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/python.py", line 1627, in runtest

    |     self.ihook.pytest_pyfunc_call(pyfuncitem=self)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_hooks.py", line 512, in __call__

    |     return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_manager.py", line 120, in _hookexec

    |     return self._inner_hookexec(hook_name, methods, kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 167, in _multicall

    |     raise exception

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 53, in run_old_style_hookwrapper

    |     return result.get_result()

    |            ^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_result.py", line 103, in get_result

    |     raise exc.with_traceback(tb)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 38, in run_old_style_hookwrapper

    |     res = yield

    |           ^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 121, in _multicall

    |     res = hook_impl.function(*args)

    |           ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/python.py", line 159, in pytest_pyfunc_call

    |     result = testfunction(**testargs)

    |              ^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/tests/test_routes.py", line 1144, in test_health_endpoint_failure

    |     response = client.get("/health/db")

    |                ^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 523, in get

    |     return super().get(

    |            ^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 1041, in get

    |     return self.request(

    |            ^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 491, in request

    |     return super().request(

    |            ^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 814, in request

    |     return self.send(request, auth=auth, follow_redirects=follow_redirects)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 901, in send

    |     response = self._send_handling_auth(

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 929, in _send_handling_auth

    |     response = self._send_handling_redirects(

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 966, in _send_handling_redirects

    |     response = self._send_single_request(request)

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 1002, in _send_single_request

    |     response = transport.handle_request(request)

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 372, in handle_request

    |     raise exc

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 369, in handle_request

    |     portal.call(self.app, scope, receive, send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py", line 326, in call

    |     return cast(T_Retval, self.start_task_soon(func, *args).result())

    |                           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py", line 449, in result

    |     return self.__get_result()

    |            ^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py", line 401, in __get_result

    |     raise self._exception

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py", line 257, in _call_func

    |     retval = await retval_or_awaitable

    |              ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/fastapi/applications.py", line 1054, in __call__

    |     await super().__call__(scope, receive, send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/applications.py", line 123, in __call__

    |     await self.middleware_stack(scope, receive, send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py", line 186, in __call__

    |     raise exc

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py", line 164, in __call__

    |     await self.app(scope, receive, _send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py", line 189, in __call__

    |     with collapse_excgroups():

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/contextlib.py", line 158, in __exit__

    |     self.gen.throw(typ, value, traceback)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/_utils.py", line 93, in collapse_excgroups

    |     raise exc

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py", line 191, in __call__

    |     response = await self.dispatch_func(request, call_next)

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/app/middleware/emergency_check.py", line 20, in dispatch

    |     controls = EmergencyControls()

    |                ^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/app/services/emergency_controls.py", line 15, in __init__

    |     self._client = client or _build_supabase_client()

    |                              ^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/app/repositories.py", line 2384, in _build_supabase_client

    |     raise RuntimeError("Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.")

    | RuntimeError: Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.

    +------------------------------------



During handling of the above exception, another exception occurred:



    def test_health_endpoint_failure() -> None:

        repo = MockRepository()

        repo.health_ok = False

        client = _build_test_client(repo)

    

>       response = client.get("/health/db")



tests/test_routes.py:1144: 

_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:523: in get

    return super().get(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:1041: in get

    return self.request(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:491: in request

    return super().request(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:814: in request

    return self.send(request, auth=auth, follow_redirects=follow_redirects)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:901: in send

    response = self._send_handling_auth(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:929: in _send_handling_auth

    response = self._send_handling_redirects(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:966: in _send_handling_redirects

    response = self._send_single_request(request)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:1002: in _send_single_request

    response = transport.handle_request(request)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:372: in handle_request

    raise exc

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:369: in handle_request

    portal.call(self.app, scope, receive, send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py:326: in call

    return cast(T_Retval, self.start_task_soon(func, *args).result())

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py:449: in result

    return self.__get_result()

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py:401: in __get_result

    raise self._exception

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py:257: in _call_func

    retval = await retval_or_awaitable

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/fastapi/applications.py:1054: in __call__

    await super().__call__(scope, receive, send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/applications.py:123: in __call__

    await self.middleware_stack(scope, receive, send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py:186: in __call__

    raise exc

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py:164: in __call__

    await self.app(scope, receive, _send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py:189: in __call__

    with collapse_excgroups():

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/contextlib.py:158: in __exit__

    self.gen.throw(typ, value, traceback)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/_utils.py:93: in collapse_excgroups

    raise exc

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py:191: in __call__

    response = await self.dispatch_func(request, call_next)

app/middleware/emergency_check.py:20: in dispatch

    controls = EmergencyControls()

app/services/emergency_controls.py:15: in __init__

    self._client = client or _build_supabase_client()

_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 



    @lru_cache(maxsize=1)

    def _build_supabase_client() -> Client:

        settings = load_supabase_settings()

        if not settings:

>           raise RuntimeError("Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.")

E           RuntimeError: Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.



app/repositories.py:2384: RuntimeError

________________________ test_cal_balance_and_mint_flow ________________________

  + Exception Group Traceback (most recent call last):

  |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/_utils.py", line 87, in collapse_excgroups

  |     yield

  |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py", line 190, in __call__

  |     async with anyio.create_task_group() as task_group:

  |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/_backends/_asyncio.py", line 783, in __aexit__

  |     raise BaseExceptionGroup(

  | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)

  +-+---------------- 1 ----------------

    | Traceback (most recent call last):

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/runner.py", line 341, in from_call

    |     result: TResult | None = func()

    |                              ^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/runner.py", line 242, in <lambda>

    |     lambda: runtest_hook(item=item, **kwds), when=when, reraise=reraise

    |             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_hooks.py", line 512, in __call__

    |     return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_manager.py", line 120, in _hookexec

    |     return self._inner_hookexec(hook_name, methods, kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 167, in _multicall

    |     raise exception

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/threadexception.py", line 92, in pytest_runtest_call

    |     yield from thread_exception_runtest_hook()

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/threadexception.py", line 68, in thread_exception_runtest_hook

    |     yield

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/unraisableexception.py", line 95, in pytest_runtest_call

    |     yield from unraisable_exception_runtest_hook()

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/unraisableexception.py", line 70, in unraisable_exception_runtest_hook

    |     yield

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/logging.py", line 848, in pytest_runtest_call

    |     yield from self._runtest_for(item, "call")

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/logging.py", line 831, in _runtest_for

    |     yield

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/capture.py", line 879, in pytest_runtest_call

    |     return (yield)

    |             ^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/skipping.py", line 257, in pytest_runtest_call

    |     return (yield)

    |             ^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 121, in _multicall

    |     res = hook_impl.function(*args)

    |           ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/runner.py", line 174, in pytest_runtest_call

    |     item.runtest()

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/python.py", line 1627, in runtest

    |     self.ihook.pytest_pyfunc_call(pyfuncitem=self)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_hooks.py", line 512, in __call__

    |     return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_manager.py", line 120, in _hookexec

    |     return self._inner_hookexec(hook_name, methods, kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 167, in _multicall

    |     raise exception

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 53, in run_old_style_hookwrapper

    |     return result.get_result()

    |            ^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_result.py", line 103, in get_result

    |     raise exc.with_traceback(tb)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 38, in run_old_style_hookwrapper

    |     res = yield

    |           ^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 121, in _multicall

    |     res = hook_impl.function(*args)

    |           ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/python.py", line 159, in pytest_pyfunc_call

    |     result = testfunction(**testargs)

    |              ^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/tests/test_routes.py", line 1152, in test_cal_balance_and_mint_flow

    |     _device_id, access_token, _ = authenticate(client, repo)

    |                                   ^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/tests/test_routes.py", line 940, in authenticate

    |     nonce_res = client.post("/auth/nonce", json={"wallet": repo.wallet, "device_id": device_id})

    |                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 608, in post

    |     return super().post(

    |            ^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 1132, in post

    |     return self.request(

    |            ^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 491, in request

    |     return super().request(

    |            ^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 814, in request

    |     return self.send(request, auth=auth, follow_redirects=follow_redirects)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 901, in send

    |     response = self._send_handling_auth(

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 929, in _send_handling_auth

    |     response = self._send_handling_redirects(

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 966, in _send_handling_redirects

    |     response = self._send_single_request(request)

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 1002, in _send_single_request

    |     response = transport.handle_request(request)

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 372, in handle_request

    |     raise exc

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 369, in handle_request

    |     portal.call(self.app, scope, receive, send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py", line 326, in call

    |     return cast(T_Retval, self.start_task_soon(func, *args).result())

    |                           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py", line 449, in result

    |     return self.__get_result()

    |            ^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py", line 401, in __get_result

    |     raise self._exception

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py", line 257, in _call_func

    |     retval = await retval_or_awaitable

    |              ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/fastapi/applications.py", line 1054, in __call__

    |     await super().__call__(scope, receive, send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/applications.py", line 123, in __call__

    |     await self.middleware_stack(scope, receive, send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py", line 186, in __call__

    |     raise exc

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py", line 164, in __call__

    |     await self.app(scope, receive, _send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py", line 189, in __call__

    |     with collapse_excgroups():

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/contextlib.py", line 158, in __exit__

    |     self.gen.throw(typ, value, traceback)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/_utils.py", line 93, in collapse_excgroups

    |     raise exc

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py", line 191, in __call__

    |     response = await self.dispatch_func(request, call_next)

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/app/middleware/emergency_check.py", line 20, in dispatch

    |     controls = EmergencyControls()

    |                ^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/app/services/emergency_controls.py", line 15, in __init__

    |     self._client = client or _build_supabase_client()

    |                              ^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/app/repositories.py", line 2384, in _build_supabase_client

    |     raise RuntimeError("Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.")

    | RuntimeError: Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.

    +------------------------------------



During handling of the above exception, another exception occurred:



    def test_cal_balance_and_mint_flow() -> None:

        repo = MockRepository()

        client = _build_test_client(repo)

>       _device_id, access_token, _ = authenticate(client, repo)



tests/test_routes.py:1152: 

_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

tests/test_routes.py:940: in authenticate

    nonce_res = client.post("/auth/nonce", json={"wallet": repo.wallet, "device_id": device_id})

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:608: in post

    return super().post(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:1132: in post

    return self.request(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:491: in request

    return super().request(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:814: in request

    return self.send(request, auth=auth, follow_redirects=follow_redirects)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:901: in send

    response = self._send_handling_auth(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:929: in _send_handling_auth

    response = self._send_handling_redirects(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:966: in _send_handling_redirects

    response = self._send_single_request(request)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:1002: in _send_single_request

    response = transport.handle_request(request)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:372: in handle_request

    raise exc

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:369: in handle_request

    portal.call(self.app, scope, receive, send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py:326: in call

    return cast(T_Retval, self.start_task_soon(func, *args).result())

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py:449: in result

    return self.__get_result()

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py:401: in __get_result

    raise self._exception

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py:257: in _call_func

    retval = await retval_or_awaitable

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/fastapi/applications.py:1054: in __call__

    await super().__call__(scope, receive, send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/applications.py:123: in __call__

    await self.middleware_stack(scope, receive, send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py:186: in __call__

    raise exc

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py:164: in __call__

    await self.app(scope, receive, _send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py:189: in __call__

    with collapse_excgroups():

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/contextlib.py:158: in __exit__

    self.gen.throw(typ, value, traceback)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/_utils.py:93: in collapse_excgroups

    raise exc

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py:191: in __call__

    response = await self.dispatch_func(request, call_next)

app/middleware/emergency_check.py:20: in dispatch

    controls = EmergencyControls()

app/services/emergency_controls.py:15: in __init__

    self._client = client or _build_supabase_client()

_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 



    @lru_cache(maxsize=1)

    def _build_supabase_client() -> Client:

        settings = load_supabase_settings()

        if not settings:

>           raise RuntimeError("Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.")

E           RuntimeError: Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.



app/repositories.py:2384: RuntimeError

___________________________ test_staking_claims_flow ___________________________

  + Exception Group Traceback (most recent call last):

  |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/_utils.py", line 87, in collapse_excgroups

  |     yield

  |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py", line 190, in __call__

  |     async with anyio.create_task_group() as task_group:

  |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/_backends/_asyncio.py", line 783, in __aexit__

  |     raise BaseExceptionGroup(

  | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)

  +-+---------------- 1 ----------------

    | Traceback (most recent call last):

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/runner.py", line 341, in from_call

    |     result: TResult | None = func()

    |                              ^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/runner.py", line 242, in <lambda>

    |     lambda: runtest_hook(item=item, **kwds), when=when, reraise=reraise

    |             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_hooks.py", line 512, in __call__

    |     return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_manager.py", line 120, in _hookexec

    |     return self._inner_hookexec(hook_name, methods, kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 167, in _multicall

    |     raise exception

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/threadexception.py", line 92, in pytest_runtest_call

    |     yield from thread_exception_runtest_hook()

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/threadexception.py", line 68, in thread_exception_runtest_hook

    |     yield

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/unraisableexception.py", line 95, in pytest_runtest_call

    |     yield from unraisable_exception_runtest_hook()

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/unraisableexception.py", line 70, in unraisable_exception_runtest_hook

    |     yield

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/logging.py", line 848, in pytest_runtest_call

    |     yield from self._runtest_for(item, "call")

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/logging.py", line 831, in _runtest_for

    |     yield

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/capture.py", line 879, in pytest_runtest_call

    |     return (yield)

    |             ^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/skipping.py", line 257, in pytest_runtest_call

    |     return (yield)

    |             ^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 121, in _multicall

    |     res = hook_impl.function(*args)

    |           ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/runner.py", line 174, in pytest_runtest_call

    |     item.runtest()

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/python.py", line 1627, in runtest

    |     self.ihook.pytest_pyfunc_call(pyfuncitem=self)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_hooks.py", line 512, in __call__

    |     return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_manager.py", line 120, in _hookexec

    |     return self._inner_hookexec(hook_name, methods, kwargs, firstresult)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 167, in _multicall

    |     raise exception

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall

    |     teardown.throw(exception)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 53, in run_old_style_hookwrapper

    |     return result.get_result()

    |            ^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_result.py", line 103, in get_result

    |     raise exc.with_traceback(tb)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 38, in run_old_style_hookwrapper

    |     res = yield

    |           ^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 121, in _multicall

    |     res = hook_impl.function(*args)

    |           ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/_pytest/python.py", line 159, in pytest_pyfunc_call

    |     result = testfunction(**testargs)

    |              ^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/tests/test_routes.py", line 1173, in test_staking_claims_flow

    |     _device_id, access_token, _ = authenticate(client, repo)

    |                                   ^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/tests/test_routes.py", line 940, in authenticate

    |     nonce_res = client.post("/auth/nonce", json={"wallet": repo.wallet, "device_id": device_id})

    |                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 608, in post

    |     return super().post(

    |            ^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 1132, in post

    |     return self.request(

    |            ^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 491, in request

    |     return super().request(

    |            ^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 814, in request

    |     return self.send(request, auth=auth, follow_redirects=follow_redirects)

    |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 901, in send

    |     response = self._send_handling_auth(

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 929, in _send_handling_auth

    |     response = self._send_handling_redirects(

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 966, in _send_handling_redirects

    |     response = self._send_single_request(request)

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py", line 1002, in _send_single_request

    |     response = transport.handle_request(request)

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 372, in handle_request

    |     raise exc

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py", line 369, in handle_request

    |     portal.call(self.app, scope, receive, send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py", line 326, in call

    |     return cast(T_Retval, self.start_task_soon(func, *args).result())

    |                           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py", line 449, in result

    |     return self.__get_result()

    |            ^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py", line 401, in __get_result

    |     raise self._exception

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py", line 257, in _call_func

    |     retval = await retval_or_awaitable

    |              ^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/fastapi/applications.py", line 1054, in __call__

    |     await super().__call__(scope, receive, send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/applications.py", line 123, in __call__

    |     await self.middleware_stack(scope, receive, send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py", line 186, in __call__

    |     raise exc

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py", line 164, in __call__

    |     await self.app(scope, receive, _send)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py", line 189, in __call__

    |     with collapse_excgroups():

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/contextlib.py", line 158, in __exit__

    |     self.gen.throw(typ, value, traceback)

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/_utils.py", line 93, in collapse_excgroups

    |     raise exc

    |   File "/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py", line 191, in __call__

    |     response = await self.dispatch_func(request, call_next)

    |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/app/middleware/emergency_check.py", line 20, in dispatch

    |     controls = EmergencyControls()

    |                ^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/app/services/emergency_controls.py", line 15, in __init__

    |     self._client = client or _build_supabase_client()

    |                              ^^^^^^^^^^^^^^^^^^^^^^^^

    |   File "/home/runner/work/boulder-roller/boulder-roller/backend/app/repositories.py", line 2384, in _build_supabase_client

    |     raise RuntimeError("Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.")

    | RuntimeError: Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.

    +------------------------------------



During handling of the above exception, another exception occurred:



    def test_staking_claims_flow() -> None:

        repo = MockRepository()

        client = _build_test_client(repo)

>       _device_id, access_token, _ = authenticate(client, repo)



tests/test_routes.py:1173: 

_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

tests/test_routes.py:940: in authenticate

    nonce_res = client.post("/auth/nonce", json={"wallet": repo.wallet, "device_id": device_id})

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:608: in post

    return super().post(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:1132: in post

    return self.request(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:491: in request

    return super().request(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:814: in request

    return self.send(request, auth=auth, follow_redirects=follow_redirects)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:901: in send

    response = self._send_handling_auth(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:929: in _send_handling_auth

    response = self._send_handling_redirects(

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:966: in _send_handling_redirects

    response = self._send_single_request(request)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/httpx/_client.py:1002: in _send_single_request

    response = transport.handle_request(request)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:372: in handle_request

    raise exc

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/testclient.py:369: in handle_request

    portal.call(self.app, scope, receive, send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py:326: in call

    return cast(T_Retval, self.start_task_soon(func, *args).result())

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py:449: in result

    return self.__get_result()

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/concurrent/futures/_base.py:401: in __get_result

    raise self._exception

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/anyio/from_thread.py:257: in _call_func

    retval = await retval_or_awaitable

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/fastapi/applications.py:1054: in __call__

    await super().__call__(scope, receive, send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/applications.py:123: in __call__

    await self.middleware_stack(scope, receive, send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py:186: in __call__

    raise exc

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/errors.py:164: in __call__

    await self.app(scope, receive, _send)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py:189: in __call__

    with collapse_excgroups():

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/contextlib.py:158: in __exit__

    self.gen.throw(typ, value, traceback)

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/_utils.py:93: in collapse_excgroups

    raise exc

/opt/hostedtoolcache/Python/3.11.14/x64/lib/python3.11/site-packages/starlette/middleware/base.py:191: in __call__

    response = await self.dispatch_func(request, call_next)

app/middleware/emergency_check.py:20: in dispatch

    controls = EmergencyControls()

app/services/emergency_controls.py:15: in __init__

    self._client = client or _build_supabase_client()

_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 



    @lru_cache(maxsize=1)

    def _build_supabase_client() -> Client:

        settings = load_supabase_settings()

        if not settings:

>           raise RuntimeError("Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.")

E           RuntimeError: Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.



app/repositories.py:2384: RuntimeError

=============================== warnings summary ===============================

app/main.py:53: 1 warning

tests/test_routes.py: 14 warnings

  /home/runner/work/boulder-roller/boulder-roller/backend/app/main.py:53: UserWarning: ⚠️ AUTH_SIGNATURE_BYPASS is enabled! This should NEVER be used in production.

    warnings.warn("⚠️ AUTH_SIGNATURE_BYPASS is enabled! This should NEVER be used in production.")



-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html

=========================== short test summary info ============================

FAILED tests/test_routes.py::test_auth_flow - RuntimeError: Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.

FAILED tests/test_routes.py::test_refresh_rotates_token - RuntimeError: Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.

FAILED tests/test_routes.py::test_auth_me_returns_profile - RuntimeError: Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.

FAILED tests/test_routes.py::test_logout_revokes_refresh_token - RuntimeError: Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.

FAILED tests/test_routes.py::test_rides_proofs_and_mint_flow - RuntimeError: Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.

FAILED tests/test_routes.py::test_get_rides_returns_user_rides - RuntimeError: Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.

FAILED tests/test_routes.py::test_get_token_balances_returns_totals - RuntimeError: Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.

FAILED tests/test_routes.py::test_segments_list - RuntimeError: Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.

FAILED tests/test_routes.py::test_segments_list_with_filters - RuntimeError: Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.

FAILED tests/test_routes.py::test_segments_nearby_wraps_list - RuntimeError: Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.

FAILED tests/test_routes.py::test_health_endpoint_ok - RuntimeError: Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.

FAILED tests/test_routes.py::test_health_endpoint_failure - RuntimeError: Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.

FAILED tests/test_routes.py::test_cal_balance_and_mint_flow - RuntimeError: Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.

FAILED tests/test_routes.py::test_staking_claims_flow - RuntimeError: Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.

================== 14 failed, 16 passed, 15 warnings in 5.03s ==================

pytest-xprocess reminder::Be sure to terminate the started process by running 'pytest --xkill' if you have not explicitly done so in your fixture with 'xprocess.getinfo(<process_name>).terminate()'.

Error: Process completed with exit code 1.



0s




1s




0s





