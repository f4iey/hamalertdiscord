#!/usr/bin/env python3
import argparse
import json
import logging
import os
import re
import telnetlib
import time
from typing import Dict, Optional, Tuple

import requests
import dapnet

# DAPNET is optional and disabled by default.
DAPNET_ENABLE = os.getenv("DAPNET_ENABLE", "0").strip().lower() in {"1", "true", "yes", "on"}
DAPNET_USER = os.getenv("DAPNET_USER", "PA6ER")
DAPNET_PASSWORD = os.getenv("DAPNET_PASSWORD", "CY4HER")

# ==== Config (environment overrides supported) ====
HAMALERT_USERNAME = os.getenv("HAMALERT_USERNAME", "INSERT_USERNAME")
HAMALERT_PASSWORD = os.getenv("HAMALERT_PASSWORD", "INSERT_PASSWORD")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "INSERT_DISCORD_WEBHOOK")

HAMALERT_HOST = os.getenv("HAMALERT_HOST", "hamalert.org")
HAMALERT_PORT = int(os.getenv("HAMALERT_PORT", "7300"))

# Don’t post the same (callsign, band, mode) within this window.
DEDUP_WINDOW_SECONDS = int(os.getenv("DEDUP_WINDOW_SECONDS", str(20 * 60)))

# Set to "1" to log instead of posting to Discord (useful for testing).
DRY_RUN = os.getenv("DRY_RUN", "0") == "1"

# Track last post time per composite key.
_last_posted_at: Dict[str, float] = {}


# -------- Utility / Normalization --------
def get_first(d: dict, *keys, default=None):
    """Return the first present, non-empty value from keys in dict d."""
    for key in keys:
        value = d.get(key)
        if value is not None and str(value).strip() != "":
            return value
    return default


def _parse_mhz(value) -> Optional[float]:
    """Parse frequency into MHz. Accepts numbers or strings, kHz or MHz."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        frequency = float(value)
    else:
        match = re.search(r"(\d+(?:\.\d+)?)", str(value))
        if not match:
            return None
        frequency = float(match.group(1))
    if frequency >= 1000.0:
        frequency /= 1000.0
    return frequency


def _band_from_mhz(mhz: float) -> str:
    """Map MHz to a band label. Fall back to 'unknown'."""
    ranges = [
        (0.1357, 0.1378, "2200m"), (0.472, 0.479, "630m"),
        (1.8, 2.0, "160m"), (3.5, 4.0, "80m"), (5.330, 5.405, "60m"),
        (7.0, 7.3, "40m"), (10.1, 10.15, "30m"), (14.0, 14.35, "20m"),
        (18.068, 18.168, "17m"), (21.0, 21.45, "15m"),
        (24.89, 24.99, "12m"), (28.0, 29.7, "10m"), (50.0, 54.0, "6m"),
        (70.0, 71.0, "4m"), (144.0, 148.0, "2m"), (219.0, 225.0, "1.25m"),
        (420.0, 450.0, "70cm"), (902.0, 928.0, "33cm"),
        (1240.0, 1300.0, "23cm"),
    ]
    for lower, upper, label in ranges:
        if lower <= mhz <= upper:
            return label
    return "unknown"


def extract_band(payload: dict) -> str:
    """Prefer explicit 'band'; otherwise derive it from frequency."""
    band = str(get_first(payload, "band", "bandName", default="")).strip()
    if band:
        return band
    mhz = _parse_mhz(get_first(payload, "frequency", "freq", "frequencyMHz", "frequencyKhz"))
    return _band_from_mhz(mhz) if mhz is not None else "unknown"


# -------- Discord --------
def send_discord_webhook(content: str) -> bool:
    if DRY_RUN:
        logging.info("[DRY_RUN] Would post to Discord:\n%s", content)
        return True
    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json={"content": content}, timeout=10)
        if 200 <= response.status_code < 300:
            logging.info("Discord webhook sent (status %s).", response.status_code)
            return True
        logging.error("Discord webhook failed (status %s, body=%r).", response.status_code, response.text)
    except requests.RequestException as error:
        logging.exception("Discord webhook exception: %s", error)
    return False


def send_dapnet_spot(spot: dict) -> bool:
    """Send a HamAlert spot to DAPNET when DAPNET is enabled."""
    if not DAPNET_ENABLE:
        return True

    spotter = get_first(spot, "spotter", "reporter", "deCallsign", "de", default="?")
    callsign = get_first(spot, "callsign", "fullCallsign", "call")
    frequency = get_first(spot, "frequency", "freq", "frequencyMHz", "frequencyKhz", default="?")
    mode = get_first(spot, "mode", "opMode", "modulation", default="?")
    if not callsign:
        logging.warning("Cannot send spot to DAPNET: spot has no callsign.")
        return False

    message = f"DX de {spotter}: {callsign} on {frequency} ({mode})"
    try:
        return dapnet.send(DAPNET_USER, DAPNET_PASSWORD, message, DAPNET_USER)
    except requests.RequestException as error:
        logging.exception("DAPNET request failed: %s", error)
        return False


# -------- De-dupe (callsign | band | mode) --------
def _make_key(callsign: str, band: str, mode: str) -> str:
    return f"{callsign.strip().upper()}|{band.strip().lower()}|{mode.strip().upper()}"


def should_post(callsign: str, band: str, mode: str, now: Optional[float] = None) -> bool:
    if not callsign:
        return True
    now = time.time() if now is None else now
    last = _last_posted_at.get(_make_key(callsign, band, mode))
    if last is not None and now - last < DEDUP_WINDOW_SECONDS:
        elapsed = int(now - last)
        remaining = int(DEDUP_WINDOW_SECONDS - (now - last))
        logging.info(
            "Skip %s (%s, %s) — seen %ds ago; %ds left in de-dupe.",
            callsign.upper(), band, mode.upper(), elapsed, remaining
        )
        return False
    return True


def mark_posted(callsign: str, band: str, mode: str, when: Optional[float] = None) -> None:
    if callsign:
        _last_posted_at[_make_key(callsign, band, mode)] = time.time() if when is None else when


# -------- Message builder (robust field mapping) --------
def build_message(d: dict) -> Optional[Tuple[str, str, str, str]]:
    """Return (message, callsign, band, mode), or None when no callsign is present."""
    callsign = get_first(d, "fullCallsign", "callsign", "call")
    if not callsign:
        logging.debug("No callsign in spot; keys=%s", list(d.keys()))
        return None

    spotter = get_first(d, "spotter", "reporter", "deCallsign", "de", default="?")
    mode = str(get_first(d, "mode", "opMode", "modulation", default="?")).strip() or "?"
    frequency = get_first(d, "frequency", "freq", "frequencyMHz", "frequencyKhz")
    mhz = _parse_mhz(frequency)
    frequency_text = f"{mhz:.3f} MHz" if mhz is not None else (str(frequency) if frequency is not None else "?")
    band = extract_band(d)

    spot_time = get_first(d, "time", "timeISO", "timestamp")
    if isinstance(spot_time, (int, float)):
        time_text = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(float(spot_time)))
    else:
        time_text = str(spot_time) if spot_time else "?"

    message = f"SPOT: {callsign} seen by {spotter} on {frequency_text} ({mode}, {band}) at {time_text} UTC"
    sota_fields = {"summitName", "summitRef", "summitPoints", "summitHeight"}
    if sota_fields.issubset(d.keys()):
        message = "SOTA " + message
        message += (
            f"\nSummit: {d['summitName']} — {d['summitRef']} — "
            f"a {d['summitPoints']}-point summit at {d['summitHeight']} m!"
        )
    return message, str(callsign), band, mode


# -------- Telnet loop (robust handshake) --------
def telnet_listener(host: str, port: int, username: str, password: str) -> None:
    """Connect, switch HamAlert to JSON mode, and process streamed spots."""
    with telnetlib.Telnet(host, port, timeout=30) as connection:
        logging.info("Connected to %s:%s", host, port)
        connection.read_until(b"login:")
        connection.write((username + "\n").encode("utf-8"))
        connection.read_until(b"password:")
        connection.write((password + "\n").encode("utf-8"))

        initialized = False
        requested_json = False
        while True:
            raw = connection.read_until(b"\n", timeout=30)
            data = raw.decode("utf-8", errors="replace").strip("\r\n")
            if not data:
                try:
                    connection.write(telnetlib.IAC + telnetlib.NOP)
                    logging.debug("Sent Telnet NOP keepalive.")
                except OSError:
                    pass
                continue

            lower = data.lower()
            logging.debug("Line: %s", data)
            if "hamalert" in lower and "hello" in lower:
                continue
            if ("de hamalert" in lower or "hamalert >" in lower) and not requested_json:
                logging.info("Setting JSON mode...")
                connection.write(b"set/json\n")
                requested_json = True
                continue
            if "operation successful" in lower:
                logging.info("JSON mode confirmed.")
                initialized = True
                continue
            if not initialized:
                continue

            try:
                parsed = json.loads(data)
            except json.JSONDecodeError:
                logging.debug("Non-JSON line in JSON mode: %s", data)
                continue
            if not isinstance(parsed, dict):
                logging.debug("JSON not an object; skipping: %r", parsed)
                continue

            built = build_message(parsed)
            if not built:
                logging.debug("Spot missing essentials; skipping. Keys=%s", list(parsed.keys()))
                continue
            message, callsign, band, mode = built
            if not should_post(callsign, band, mode):
                continue

            # DAPNET delivery is optional; its failure must not block Discord delivery.
            if DAPNET_ENABLE and not send_dapnet_spot(parsed):
                logging.warning("DAPNET delivery failed for %s.", callsign)
            if send_discord_webhook(message):
                mark_posted(callsign, band, mode)


# -------- CLI / Main --------
def setup_args():
    parser = argparse.ArgumentParser(description="HamAlert → Discord bridge (robust + per-band/mode de-dupe).")
    parser.add_argument(
        "-l", "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level (default: INFO)",
    )
    parser.add_argument(
        "--reconnect-delay", type=int, default=10,
        help="Seconds to wait before reconnecting after disconnect (default: 10)",
    )
    return parser.parse_args()


def main():
    args = setup_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s | %(levelname)-8s | %(message)s",
    )

    missing = []
    if not HAMALERT_USERNAME or HAMALERT_USERNAME == "INSERT_USERNAME":
        missing.append("HAMALERT_USERNAME")
    if not HAMALERT_PASSWORD or HAMALERT_PASSWORD == "INSERT_PASSWORD":
        missing.append("HAMALERT_PASSWORD")
    if not DISCORD_WEBHOOK_URL or DISCORD_WEBHOOK_URL == "INSERT_DISCORD_WEBHOOK":
        missing.append("DISCORD_WEBHOOK_URL")
    if DAPNET_ENABLE and (not DAPNET_USER or not DAPNET_PASSWORD):
        missing.append("DAPNET_USER/DAPNET_PASSWORD")
    if missing:
        logging.warning("Missing/placeholder config for: %s", ", ".join(missing))

    while True:
        try:
            telnet_listener(HAMALERT_HOST, HAMALERT_PORT, HAMALERT_USERNAME, HAMALERT_PASSWORD)
        except ConnectionRefusedError:
            logging.error("Telnet connection refused. Is the server reachable?")
        except Exception as error:
            logging.exception("Unhandled error: %s", error)
        logging.info("Reconnecting in %d seconds...", args.reconnect_delay)
        time.sleep(args.reconnect_delay)


if __name__ == "__main__":
    main()
