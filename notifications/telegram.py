"""Async Telegram notification system with queue, rate limiting, retries, and rich formatting."""
import time
import threading
import queue
from typing import Optional, List

import requests

from config import TELEGRAM_MAX_RATE, TELEGRAM_MAX_RETRIES, RETRY_BACKOFF_BASE
from utils.logger import get_logger

log = get_logger("telegram")


class TelegramNotifier:
    """Thread-safe singleton Telegram notifier with background send queue.

    Features:
        - Background thread processes a message queue (non-blocking sends)
        - Rate limiting: max TELEGRAM_MAX_RATE messages per minute
        - Retry logic: TELEGRAM_MAX_RETRIES attempts with exponential backoff
        - Rich formatting methods for signal alerts, exit alerts, daily reports
        - Graceful fallback when Streamlit secrets are not configured
    """

    _instance: Optional["TelegramNotifier"] = None
    _init_lock = threading.Lock()

    # ── singleton ────────────────────────────────────────────────────────
    def __new__(cls) -> "TelegramNotifier":
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True

        import os

        # Read secrets — graceful fallback
        self._token: Optional[str] = None
        self._chat_id: Optional[str] = None
        try:
            self._token = os.environ.get("TELEGRAM_TOKEN")
            self._chat_id = os.environ.get("TELEGRAM_CHAT_ID")
        except Exception:
            log.warning("Environment variables not available — Telegram disabled")

        if not self._token or not self._chat_id:
            log.warning("TELEGRAM_TOKEN / TELEGRAM_CHAT_ID not set — notifications disabled")
            self._enabled = False
        else:
            self._enabled = True

        # Queue & rate-limit state
        self._queue: queue.Queue = queue.Queue()
        self._send_times: list = []  # timestamps of recent sends for rate limiting
        self._lock = threading.Lock()

        # Start background worker (daemon so it dies with the main process)
        self._worker_thread = threading.Thread(target=self._worker, name="tg-sender", daemon=True)
        self._worker_thread.start()
        log.info("TelegramNotifier initialised (enabled=%s)", self._enabled)

    # ── public API ───────────────────────────────────────────────────────
    def send(self, msg: str, parse_mode: str = "Markdown") -> None:
        """Queue a raw message for background delivery."""
        if not self._enabled:
            log.debug("Telegram disabled — message dropped")
            return
        self._queue.put((msg, parse_mode))

    def send_signal_alert(
        self,
        idx: str,
        signal: str,
        strike: str,
        spot: str,
        entry: str,
        sl: str,
        tgt: str,
        qty: str,
        ml: str,
        tp: str,
        conf: str,
        score: str,
        time_str: str,
    ) -> None:
        """Send a richly-formatted signal alert."""
        msg = (
            "━━━━━━━━━━━━━━━━━━\n"
            f"🟢 V12 SIGNAL — {idx}\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"📊 Signal: {signal}\n"
            f"📍 Strike: {strike} | Spot: {spot}\n"
            f"💰 Entry: ₹{entry}\n"
            f"🔴 Stop Loss: ₹{sl}\n"
            f"🎯 Target: ₹{tgt}\n"
            f"📦 Qty: {qty} (1 Lot) | Max Loss: ₹{ml}\n"
            f"💯 Confidence: {conf} (Score: {score}/100)\n"
            f"⏰ {time_str}\n"
            "━━━━━━━━━━━━━━━━━━"
        )
        self.send(msg)

    def send_exit_alert(
        self,
        idx: str,
        signal: str,
        result_emoji: str,
        result_text: str,
        strike: str,
        entry: str,
        exit_price: str,
        pnl: str,
        time_str: str,
    ) -> None:
        """Send a richly-formatted exit / close alert."""
        msg = (
            "━━━━━━━━━━━━━━━━━━\n"
            f"{result_emoji} {result_text} — {idx} {signal}\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"📍 Strike: {strike}\n"
            f"💰 Entry: ₹{entry} → Exit: ₹{exit_price}\n"
            f"💸 P&L: ₹{pnl}\n"
            f"⏰ {time_str}\n"
            "━━━━━━━━━━━━━━━━━━"
        )
        self.send(msg)

    def send_daily_report(self, report_lines: List[str]) -> None:
        """Send a daily performance report (list of pre-formatted lines)."""
        header = (
            "━━━━━━━━━━━━━━━━━━\n"
            "📋 V12 DAILY REPORT\n"
            "━━━━━━━━━━━━━━━━━━\n"
        )
        body = "\n".join(report_lines)
        footer = "\n━━━━━━━━━━━━━━━━━━"
        self.send(header + body + footer)

    # ── background worker ────────────────────────────────────────────────
    def _worker(self) -> None:
        """Background loop: pull messages from the queue and send them."""
        log.debug("Telegram worker thread started")
        while True:
            try:
                msg, parse_mode = self._queue.get()  # blocks until item available
                self._wait_for_rate_limit()
                self._do_send(msg, parse_mode)
                self._queue.task_done()
            except Exception:
                log.exception("Unexpected error in Telegram worker loop")
                time.sleep(1)  # prevent tight error loops

    # ── rate limiting ────────────────────────────────────────────────────
    def _wait_for_rate_limit(self) -> None:
        """Block until we are under TELEGRAM_MAX_RATE msgs/minute."""
        while True:
            now = time.time()
            with self._lock:
                # Prune timestamps older than 60 s
                self._send_times = [t for t in self._send_times if now - t < 60]
                if len(self._send_times) < TELEGRAM_MAX_RATE:
                    self._send_times.append(now)
                    return
                # Need to wait — calculate how long until oldest entry expires
                wait = 60 - (now - self._send_times[0]) + 0.1
            log.debug("Rate-limited — sleeping %.1f s", wait)
            time.sleep(wait)

    # ── actual HTTP send with retry ──────────────────────────────────────
    def _do_send(self, msg: str, parse_mode: str) -> None:
        """POST message to Telegram Bot API with exponential-backoff retry."""
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        payload = {
            "chat_id": self._chat_id,
            "text": msg,
            "parse_mode": parse_mode,
        }

        for attempt in range(1, TELEGRAM_MAX_RETRIES + 1):
            try:
                resp = requests.post(url, json=payload, timeout=10)
                if resp.status_code == 200:
                    log.debug("Telegram message sent (attempt %d)", attempt)
                    return
                # Telegram error — may be transient (429, 5xx)
                log.warning(
                    "Telegram API error %s on attempt %d: %s",
                    resp.status_code,
                    attempt,
                    resp.text[:200],
                )
            except requests.RequestException as exc:
                log.warning("Telegram request failed (attempt %d): %s", attempt, exc)

            if attempt < TELEGRAM_MAX_RETRIES:
                backoff = RETRY_BACKOFF_BASE ** attempt
                log.debug("Retrying in %.1f s …", backoff)
                time.sleep(backoff)

        log.error("Telegram send failed after %d attempts — message dropped", TELEGRAM_MAX_RETRIES)
