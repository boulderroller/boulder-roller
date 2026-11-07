import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Callable, Awaitable

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message
from dotenv import load_dotenv
import httpx
import textwrap
from pythonjsonlogger import jsonlogger

from backend_client import BackendClient, generate_device_id
from storage import Storage
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
import uvicorn


load_dotenv()

log_handler = logging.StreamHandler()
log_formatter = jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
log_handler.setFormatter(log_formatter)
logger = logging.getLogger("bot")
logger.setLevel(logging.INFO)
logger.handlers.clear()
logger.addHandler(log_handler)
logger.propagate = False
logging.getLogger("httpx").setLevel(logging.WARNING)

# Ensure an event loop is available before aiogram constructs locks (uvloop may raise otherwise on macOS/Python 3.9)
asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
if asyncio.get_event_loop().is_closed():
    asyncio.set_event_loop(asyncio.new_event_loop())

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
BACKEND_API_URL = os.getenv("BACKEND_API_URL", "https://api.boulderroller.org")
DATABASE_URL = os.getenv("DATABASE_URL")  # optional: postgres/supabase dsn for bot_links
USE_POLLING = os.getenv("USE_POLLING", "true").lower() == "true"
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
WEBHOOK_SECRET_TOKEN = os.getenv("WEBHOOK_SECRET_TOKEN", "")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8081"))
NOTIFY_INTERVAL_SECONDS = int(os.getenv("NOTIFY_INTERVAL_SECONDS", "180"))
SOLSCAN_BASE = os.getenv("SOLSCAN_BASE", "https://solscan.io")


bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

backend = BackendClient(BACKEND_API_URL)
storage: Optional[Storage] = None
memory_links: Dict[int, Dict[str, Any]] = {}
pending_auth: Dict[int, Dict[str, Any]] = {}  # chat_id -> {"wallet": str, "nonce": str, "device_id": str}
notification_state: Dict[int, Dict[str, Any]] = {}
background_tasks: list[asyncio.Task] = []


async def save_link(chat_id: int, wallet: str, access: str, refresh: str, notify: bool = False):
    if storage:
        await storage.upsert_link(chat_id, wallet, access, refresh, notify)
    else:
        memory_links[chat_id] = {
            "chat_id": chat_id,
            "wallet": wallet,
            "access_token": access,
            "refresh_token": refresh,
            "notify": notify,
        }


async def get_link(chat_id: int) -> Optional[Dict[str, Any]]:
    if storage:
        return await storage.get_link(chat_id)
    return memory_links.get(chat_id)


async def set_notify(chat_id: int, notify: bool):
    if storage:
        await storage.set_notify(chat_id, notify)
    else:
        if chat_id in memory_links:
            memory_links[chat_id]["notify"] = notify


async def delete_link(chat_id: int):
    if storage:
        await storage.delete_link(chat_id)
    memory_links.pop(chat_id, None)


async def ensure_access_token(chat_id: int) -> Optional[str]:
    link = await get_link(chat_id)
    if not link:
        return None
    access = link.get("access_token")
    refresh = link.get("refresh_token")
    if not access:
        return None
    # Try a lightweight call? Instead, refresh only on failure in handlers.
    return access


async def refresh_tokens(chat_id: int) -> Optional[str]:
    link = await get_link(chat_id)
    if not link:
        return None
    refresh = link.get("refresh_token")
    if not refresh:
        return None
    device_id = generate_device_id(chat_id)
    new_tokens = await backend.refresh(refresh, device_id)
    access_token = new_tokens.get("access_token")
    refresh_token = new_tokens.get("refresh_token") or refresh
    await save_link(chat_id, link["wallet"], access_token, refresh_token, link.get("notify", False))
    return access_token


async def with_refresh(chat_id: int, func: Callable[[str], Awaitable[Any]]):
    access = await ensure_access_token(chat_id)
    try:
        return await func(access)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 401:
            new_access = await refresh_tokens(chat_id)
            if new_access:
                return await func(new_access)
        raise


def _parse_iso(dt: Optional[str]) -> Optional[datetime]:
    if not dt:
        return None
    try:
        return datetime.fromisoformat(dt.replace("Z", "+00:00"))
    except Exception:
        return None


def _human_eta(target: datetime) -> str:
    now = datetime.now(timezone.utc)
    delta = target - now
    seconds = int(delta.total_seconds())
    if seconds <= 0:
        return "now"
    minutes = seconds // 60
    hours = minutes // 60
    if hours:
        return f"in {hours}h {minutes % 60}m"
    if minutes:
        return f"in {minutes}m"
    return f"in {seconds}s"


def solscan_url(signature: Optional[str]) -> Optional[str]:
    if not signature:
        return None
    return f"{SOLSCAN_BASE.rstrip('/')}/tx/{signature}"


def format_kcal_response(data: Dict[str, Any]) -> str:
    cal_balance = data.get("cal_balance") or 0
    earned = data.get("cal_earned_today") or 0
    next_airdrop = _parse_iso(data.get("next_airdrop_at"))
    eta = _human_eta(next_airdrop) if next_airdrop else "unknown"
    return textwrap.dedent(
        f"""kCAL balance: {cal_balance:,.0f}
        earned today: {earned:,.0f}
        next airdrop: {eta if next_airdrop else 'not scheduled'}"""
    ).strip()


def format_ride_summary(ride: Dict[str, Any], status: Optional[Dict[str, Any]] = None) -> str:
    ride_id = ride.get("ride_id") or ride.get("id")
    metrics = (status or {}).get("metrics") or ride
    distance_m = metrics.get("distance_m")
    elev_m = metrics.get("elevation_gain_m")
    kcals = metrics.get("kcals")
    tss = metrics.get("tss")
    dung = (status or {}).get("dung_minted") or ride.get("dung_minted")
    sig = (status or {}).get("tx_signature")

    parts = [f"Ride {ride_id} processed."]
    metric_bits = []
    if distance_m:
        metric_bits.append(f"{distance_m/1000:.1f} km")
    if elev_m:
        metric_bits.append(f"{elev_m:.0f} m gain")
    if kcals:
        metric_bits.append(f"{kcals:.0f} kcal")
    if tss:
        metric_bits.append(f"TSS {tss:.0f}")
    if metric_bits:
        parts.append(" • ".join(metric_bits))
    if dung:
        parts.append(f"DUNG minted: {int(dung):,}")
    if sig:
        sig_line = f"Tx: {sig}"
        scan = solscan_url(sig)
        if scan:
            sig_line += f" ({scan})"
        parts.append(sig_line)
    return "\n".join(parts)


@dp.message(Command("start", "help"))
async def cmd_start(message: Message):
    await message.answer(
        "Welcome to the Boulder Rollers bot.\n"
        "Commands:\n"
        "/link – link your wallet (or /link <wallet>)\n"
        "/upload – send a FIT/GPX/TCX file\n"
        "/dung – DUNG balance\n"
        "/kcal – kCAL balance\n"
        "/claims – staking claims\n"
        "/notify on|off\n"
        "/unlink"
    )


@dp.message(Command("link"))
async def cmd_link(message: Message):
    pending_auth.pop(message.chat.id, None)
    pending_auth[message.chat.id] = {}
    parts = message.text.split(maxsplit=1)
    if len(parts) > 1:
        # Pre-seeded wallet, trigger nonce flow immediately
        wallet = parts[1].strip()
        device_id = generate_device_id(message.chat.id)
        try:
            nonce_payload = await backend.get_nonce(wallet, device_id)
            nonce = nonce_payload.get("nonce")
            message_to_sign = nonce_payload.get("message") or nonce
            pending_auth[message.chat.id] = {
                "wallet": wallet,
                "nonce": nonce,
                "device_id": device_id,
                "message": message_to_sign,
            }
            await message.answer(
                f"Nonce for {wallet[:8]}…: `{nonce}`\nSign this message in your wallet:\n\n{message_to_sign}\n\nPaste the signature here."
            )
            return
        except Exception as exc:
            pending_auth.pop(message.chat.id, None)
            await message.answer(f"Failed to get nonce: {exc}")
            return
    await message.answer(
        "Send your Solana wallet address to link. You'll then be asked to sign a nonce message in your wallet."
    )


@dp.message(Command("unlink"))
async def cmd_unlink(message: Message):
    await delete_link(message.chat.id)
    await message.answer("Unlinked. Use /link to connect again.")


@dp.message(Command("dung"))
async def cmd_dung(message: Message):
    link = await get_link(message.chat.id)
    if not link:
        await message.answer("Not linked. Use /link first.")
        return
    try:
        balances = await with_refresh(message.chat.id, lambda token: backend.get_token_balances(token))
        rides = await with_refresh(message.chat.id, lambda token: backend.list_rides(token))
        last_minted = next((r.get("dung_minted") for r in rides if r.get("dung_minted")), None) if rides else None
        msg_lines = [
            f"DUNG: {balances.get('dung', 0):,}",
            f"Total kCAL earned: {balances.get('kcal', 0):,}",
        ]
        if last_minted:
            msg_lines.append(f"Most recent ride minted: {int(last_minted):,} DUNG")
        await message.answer("\n".join(msg_lines))
    except Exception as exc:
        await message.answer(f"Error fetching balances: {exc}")


@dp.message(Command("kcal"))
async def cmd_kcal(message: Message):
    link = await get_link(message.chat.id)
    if not link:
        await message.answer("Not linked. Use /link first.")
        return
    try:
        cal = await with_refresh(message.chat.id, lambda token: backend.get_kcal_balance(token))
        if isinstance(cal, dict):
            await message.answer(format_kcal_response(cal))
        else:
            await message.answer(f"kCAL balance: {cal}")
    except Exception as exc:
        await message.answer(f"Error fetching kCAL: {exc}")


@dp.message(Command("claims"))
async def cmd_claims(message: Message):
    link = await get_link(message.chat.id)
    if not link:
        await message.answer("Not linked. Use /link first.")
        return
    try:
        claims = await with_refresh(message.chat.id, lambda token: backend.get_claims(token))
        pending = await with_refresh(message.chat.id, lambda token: backend.get_pending_rewards(token))
        lines = []
        for claim in claims.get("claims", []):
            seg = claim.get("segment_id")
            amt = claim.get("amount")
            lp = claim.get("lp_tokens")
            tx = claim.get("tx_signature")
            tx_line = f" tx={tx}" if tx else ""
            scan = solscan_url(tx)
            if scan:
                tx_line += f" ({scan})"
            lines.append(f"Segment {seg}: staked={amt}, lp={lp}{tx_line}")

        pending_list = pending.get("pending_rewards") if isinstance(pending, dict) else None
        if pending_list:
            pending_lines = [f"Pending rewards: {sum(p.get('pending_dung', 0) for p in pending_list):,} DUNG"]
            for p in pending_list[:5]:
                pending_lines.append(f"- {p.get('segment_id')}: {p.get('pending_dung', 0):,} DUNG")
            lines.append("\n".join(pending_lines))

        await message.answer("\n".join(lines) or "No claims.")
    except Exception as exc:
        await message.answer(f"Error fetching claims: {exc}")


@dp.message(Command("notify"))
async def cmd_notify(message: Message):
    parts = message.text.split()
    if len(parts) < 2 or parts[1].lower() not in {"on", "off"}:
        await message.answer("Usage: /notify on|off")
        return
    enable = parts[1].lower() == "on"
    await set_notify(message.chat.id, enable)
    await message.answer(f"Notifications {'enabled' if enable else 'disabled'} for this chat.")


@dp.message(Command("segment"))
async def cmd_segment(message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Usage: /segment <search terms>")
        return
    query = parts[1]
    link = await get_link(message.chat.id)
    if not link:
        await message.answer("Not linked. Use /link first.")
        return
    try:
        data = await with_refresh(
            message.chat.id,
            lambda token: backend.list_segments(query, token),
        )
        segs = data.get("segments") or []
        lines = []
        for seg in segs[:5]:
            lines.append(f"{seg.get('name')} (id: {seg.get('id')})")
        await message.answer("\n".join(lines) if lines else "No segments found.")
    except Exception as exc:
        await message.answer(f"Error searching segments: {exc}")


@dp.message(F.document)
async def handle_upload(message: Message):
    link = await get_link(message.chat.id)
    if not link:
        await message.answer("Not linked. Use /link first.")
        return

    doc = message.document
    file_type = (doc.file_name or "").split(".")[-1].lower()
    if file_type not in {"fit", "gpx", "tcx"}:
        await message.answer("Unsupported file. Send a FIT, GPX, or TCX file.")
        return

    file = await bot.get_file(doc.file_id)
    file_bytes = await bot.download_file(file.file_path)
    # Read bytes once - lambda may be called twice on token refresh
    file_data = file_bytes.read() if hasattr(file_bytes, 'read') else file_bytes

    await message.answer("Uploading your ride…")
    try:
        upload_res = await with_refresh(
            message.chat.id,
            lambda token: backend.upload_ride(file_data, file_type, token),
        )
        ride_id = upload_res.get("ride_id") or upload_res.get("rideId")
        await message.answer(f"Ride uploaded: {ride_id}. Checking status…")
        status = {}
        for _ in range(10):
            try:
                status = await with_refresh(
                    message.chat.id,
                    lambda token: backend.get_ride_status(ride_id, token),
                )
                if status.get("status") in {"completed", "ready"}:
                    break
            except Exception:
                pass
            await asyncio.sleep(3)
        summary = format_ride_summary({"ride_id": ride_id}, status)
        errors = status.get("errors") or status.get("error_message")
        if errors:
            summary += f"\nErrors: {errors}"
        await message.answer(summary, disable_web_page_preview=True)
        segments = await with_refresh(
            message.chat.id,
            lambda token: backend.get_ride_segments(ride_id, token),
        )
        seg_lines = []
        for seg in segments.get("segments", []):
            name = seg.get("name") or seg.get("segment_name")
            effort = seg.get("effort_score") or seg.get("elapsed_time") or ""
            seg_lines.append(f"- {name}: {effort}")
        await message.answer("Matched segments:\n" + ("\n".join(seg_lines) if seg_lines else "None"))

        # Simple DUNG/kCAL follow-up if available
        try:
            balances = await with_refresh(
                message.chat.id,
                lambda token: backend.get_token_balances(token),
            )
            cal = await with_refresh(
                message.chat.id,
                lambda token: backend.get_kcal_balance(token),
            )
            dung = balances.get("dung", 0)
            kcal = cal.get("cal_balance") if isinstance(cal, dict) else cal
            cal_line = format_kcal_response(cal) if isinstance(cal, dict) else f"kCAL: {kcal}"
            await message.answer(f"Current balances — DUNG: {dung:,}\n{cal_line}")
        except Exception:
            pass
    except Exception as exc:
        detail = ""
        if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
            try:
                detail_json = exc.response.json()
                detail = f"\nServer said: {detail_json}"
            except Exception:
                detail = f"\nServer said: {exc.response.text}"
        payload = f"Upload failed: {exc}{detail}"
        if len(payload) > 900:  # Telegram limit safeguard
            payload = payload[:900] + "…"
        await message.answer(payload)


@dp.message(F.text)
async def handle_text(message: Message):
    chat_id = message.chat.id
    text = message.text.strip()

    # Auth flow
    if chat_id in pending_auth:
        pending = pending_auth[chat_id]
        if "nonce" not in pending:
            # expecting wallet
            wallet = text
            device_id = generate_device_id(chat_id)
            try:
                nonce_payload = await backend.get_nonce(wallet, device_id)
                nonce = nonce_payload.get("nonce")
                message_to_sign = nonce_payload.get("message") or nonce
                pending_auth[chat_id] = {
                    "wallet": wallet,
                    "nonce": nonce,
                    "device_id": device_id,
                    "message": message_to_sign,
                }
                await message.answer(
                    f"Nonce: `{nonce}`\nSign this message in your wallet and paste the signature here:\n\n{message_to_sign}"
                )
            except Exception as exc:
                pending_auth.pop(chat_id, None)
                await message.answer(f"Failed to get nonce: {exc}")
        else:
            # expecting signature
            signature = text
            wallet = pending["wallet"]
            device_id = pending["device_id"]
            nonce = pending["nonce"]
            msg_for_sig = pending.get("message")
            try:
                tokens = await backend.verify_signature(wallet, signature, nonce, device_id)
                access = tokens.get("access_token")
                refresh = tokens.get("refresh_token")
                await save_link(chat_id, wallet, access, refresh)
                pending_auth.pop(chat_id, None)
                await message.answer(f"Linked to {wallet[:8]}…")
            except Exception as exc:
                extra = f"\n\nMake sure you signed exactly the provided message:\n\n{msg_for_sig}" if msg_for_sig else ""
                await message.answer(f"Verification failed: {exc}{extra}")
        return

    # No pending auth; ignore or provide hint
    if text.lower() in {"link", "wallet"}:
        await message.answer("Use /link to start linking your wallet.")


async def process_notifications_for_chat(chat_id: int):
    link = await get_link(chat_id)
    if not link or not link.get("notify"):
        return

    state = notification_state.setdefault(chat_id, {"rides": set(), "airdrop_notified": None, "pending_hash": None})

    # Ride completions
    try:
        rides = await with_refresh(chat_id, lambda token: backend.list_rides(token))
    except Exception as exc:
        logger.warning("list_rides failed", exc_info=exc, extra={"chat_id": chat_id})
        rides = []

    for ride in rides or []:
        status_value = ride.get("status") or ride.get("processing_status")
        ride_id = str(ride.get("id") or ride.get("ride_id") or "")
        if not ride_id or status_value != "completed" or ride_id in state["rides"]:
            continue
        ride_status = None
        try:
            ride_status = await with_refresh(chat_id, lambda token: backend.get_ride_status(ride_id, token))
        except Exception as exc:  # noqa: PERF203
            logger.info("ride status lookup failed", extra={"chat_id": chat_id, "ride_id": ride_id, "error": str(exc)})
        summary = format_ride_summary({"ride_id": ride_id, **ride}, ride_status or {})
        await bot.send_message(chat_id, summary, disable_web_page_preview=True)
        state["rides"].add(ride_id)

    # kCAL airdrop timing
    try:
        cal = await with_refresh(chat_id, lambda token: backend.get_kcal_balance(token))
        next_airdrop = _parse_iso(cal.get("next_airdrop_at")) if isinstance(cal, dict) else None
        if next_airdrop and next_airdrop <= datetime.now(timezone.utc):
            marker = next_airdrop.isoformat()
            if state.get("airdrop_notified") != marker:
                await bot.send_message(
                    chat_id,
                    f"kCAL airdrop ready.\n{format_kcal_response(cal)}",
                    disable_web_page_preview=True,
                )
                state["airdrop_notified"] = marker
    except Exception as exc:
        logger.info("cal balance check failed", extra={"chat_id": chat_id, "error": str(exc)})

    # Pending staking rewards
    try:
        pending = await with_refresh(chat_id, lambda token: backend.get_pending_rewards(token))
        pending_list = pending.get("pending_rewards") if isinstance(pending, dict) else None
        if pending_list:
            payload_key = tuple(sorted((p.get("segment_id"), p.get("pending_dung", 0)) for p in pending_list))
            if payload_key != state.get("pending_hash"):
                lines = ["Pending staking rewards:"]
                total = sum(p.get("pending_dung", 0) for p in pending_list)
                lines.append(f"Total: {total:,} DUNG")
                for p in pending_list[:5]:
                    lines.append(f"- {p.get('segment_id')}: {p.get('pending_dung', 0):,} DUNG")
                await bot.send_message(chat_id, "\n".join(lines))
                state["pending_hash"] = payload_key
        else:
            state["pending_hash"] = None
    except Exception as exc:
        logger.info("pending rewards check failed", extra={"chat_id": chat_id, "error": str(exc)})


async def notification_loop():
    if NOTIFY_INTERVAL_SECONDS <= 0:
        logger.info("Notification loop disabled")
        return
    logger.info("Notification loop started", extra={"interval": NOTIFY_INTERVAL_SECONDS})
    try:
        while True:
            links = []
            if storage:
                try:
                    links = await storage.list_links()
                except Exception as exc:  # noqa: PERF203
                    logger.warning("Failed to list links", exc_info=exc)
            else:
                links = list(memory_links.values())
            for link in links:
                if not link.get("notify"):
                    continue
                try:
                    await process_notifications_for_chat(int(link.get("chat_id")))
                except Exception as exc:  # noqa: PERF203
                    logger.warning("Notification cycle failed", exc_info=exc, extra={"chat_id": link.get("chat_id")})
            await asyncio.sleep(NOTIFY_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        logger.info("Notification loop cancelled")
        raise


async def on_startup():
    global storage
    if DATABASE_URL:
        storage = Storage(DATABASE_URL)
        await storage.connect()
    else:
        logger.warning("No DATABASE_URL set; link state will not persist.")


async def on_shutdown():
    await backend.close()
    if storage:
        await storage.close()


async def run_polling():
    await on_startup()
    if NOTIFY_INTERVAL_SECONDS > 0:
        background_tasks.append(asyncio.create_task(notification_loop()))
    try:
        await dp.start_polling(bot)
    finally:
        for task in background_tasks:
            task.cancel()
        if background_tasks:
            await asyncio.gather(*background_tasks, return_exceptions=True)
        await on_shutdown()


def main():
    if USE_POLLING:
        asyncio.run(run_polling())
    else:
        app = FastAPI()
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        @app.on_event("startup")
        async def startup_event():
            await on_startup()
            if WEBHOOK_URL:
                await bot.set_webhook(WEBHOOK_URL, secret_token=WEBHOOK_SECRET_TOKEN)
            if NOTIFY_INTERVAL_SECONDS > 0:
                background_tasks.append(asyncio.create_task(notification_loop()))

        @app.on_event("shutdown")
        async def shutdown_event():
            await bot.delete_webhook()
            for task in background_tasks:
                task.cancel()
            if background_tasks:
                await asyncio.gather(*background_tasks, return_exceptions=True)
            await on_shutdown()

        @app.post("/bot/webhook")
        async def telegram_webhook(request: Request):
            # Verify secret token if set
            if WEBHOOK_SECRET_TOKEN:
                header_token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
                if header_token != WEBHOOK_SECRET_TOKEN:
                    return Response(status_code=401)
            update = await request.json()
            await dp.feed_webhook_update(bot, update)
            return Response(status_code=200)

        uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
