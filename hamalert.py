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
import os
import dapnet

# If using dapnet
DAPNET_ENABLE = os.getenv('DAPNET_ENABLE', '0')
DAPNET_USER = os.getenv('DAPNET_USER', 'PA6ER')
DAPNET_PASSWORD = os.getenv('DAPNET_PASSWORD', 'CY4HER')

# ==== Config (env overrides supported) ====
HAMALERT_USERNAME = os.getenv("HAMALERT_USERNAME", "INSERT_USERNAME")
HAMALERT_PASSWORD = os.getenv("HAMALERT_PASSWORD", "INSERT_PASSWORD")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "INSERT_DISCORD_WEBHOOK")

HAMALERT_HOST = os.getenv("HAMALERT_HOST", "hamalert.org")
HAMALERT_PORT = int(os.getenv("HAMALERT_PORT", "7300"))

# Don’t post the same (callsign, band, mode) within this window
DEDUP_WINDOW_SECONDS = int(os.getenv("DEDUP_WINDOW_SECONDS", str(20 * 60)))  # 20 min

# Set to "1" to log instead of posting to Discord (useful for testing)
DRY_RUN = os.getenv("DRY_RUN", "0") == "1"

# Track last post time per composite key
_last_posted_at: Dict[str, float] = {}

# -------- Utility / Normalization --------
def get_first(d: dict, *keys, default=None):
    """Return the first present, non-empty value from keys in dict d."""
    for k in keys:
        v = d.get(k)
        if v is not None and str(v).strip() != "":
            return v
    return default

def _parse_mhz(val) -> Optional[float]:
    """
    Parse frequency into MHz. Accepts numbers or strings, kHz or MHz.
    Heuristic: >= 1000 -> kHz (divide by 1000).
    """
    if val is None:
        return None
    if isinstance(val, (int, float)):
        f = float(val)
    else:
        m = re.search(r"(\d+(?:\.\d+)?)", str(val))
        if not m:
            return None
        f = float(m.group(1))
    if f >= 1000.0:
        f /= 1000.0
    return f

def _band_from_mhz(mhz: float) -> str:
    """
    Map MHz to band label (US-centric). Fallback 'unknown'.
    """
    ranges = [
        (0.1357, 0.1378, "2200m"),
        (0.472, 0.479, "630m"),
        (1.8, 2.0, "160m"),
        (3.5, 4.0, "80m"),
        (5.330, 5.405, "60m"),
        (7.0, 7.3, "40m"),
        (10.1, 10.15, "30m"),
        (14.0, 14.35, "20m"),
        (18.068, 18.168, "17m"),
        (21.0, 21.45, "15m"),
        (24.89, 24.99, "12m"),
        (28.0, 29.7, "10m"),
        (50.0, 54.0, "6m"),
        (70.0, 71.0, "4m"),
        (144.0, 148.0, "2m"),
        (219.0, 225.0, "1.25m"),
        (420.0, 450.0, "70cm"),
        (902.0, 928.0, "33cm"),
        (1240.0, 1300.0, "23cm"),
    ]
    for lo, hi, label in ranges:
        if lo <= mhz <= hi:
            return label
    return "unknown"

def extract_band(payload: dict) -> str:
    """Prefer explicit 'band' if present; otherwise derive from frequency."""
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
        resp = requests.post(DISCORD_WEBHOOK_URL, json={"content": content}, timeout=10)
        if 200 <= resp.status_code < 300 or resp.status_code == 204:
            logging.info("Discord webhook sent (status %s).", resp.status_code)
            return True
        logging.error("Discord webhook failed (status %s, body=%r).", resp.status_code, resp.text)
        return False
    except requests.RequestException as e:
        logging.exception("Discord webhook exception: %s", e)
        return False

# -------- De-dupe (callsign | band | mode) --------
def _make_key(callsign: str, band: str, mode: str) -> str:
    return f"{callsign.strip().upper()}|{band.strip().lower()}|{mode.strip().upper()}"

def should_post(callsign: str, band: str, mode: str, now: Optional[float] = None) -> bool:
    if not callsign:
        return True
    now = time.time() if now is None else now
    key = _make_key(callsign, band, mode)
    last = _last_posted_at.get(key)
    if last is not None and (now - last) < DEDUP_WINDOW_SECONDS:
        remaining = int(DEDUP_WINDOW_SECONDS - (now - last))
        logging.info(
            "Skip %s (%s, %s) — seen %ds ago; %ds left in de-dupe.",
            callsign.upper(), band, mode.upper(), int(now - last), remaining
        )
        return False
    return True

def mark_posted(callsign: str, band: str, mode: str, when: Optional[float] = None) -> None:
    if not callsign:
        return
    _last_posted_at[_make_key(callsign, band, mode)] = time.time() if when is None else when

# -------- Message builder (robust field mapping) --------
def build_message(d: dict) -> Optional[Tuple[str, str, str, str]]:
    """
    Build Discord message from a HamAlert spot dict.
    Returns (message, callsign, band, mode) or None if no callsign/freq/mode at all.
    """
    callsign = get_first(d, "fullCallsign", "callsign", "call")
    if not callsign:
        logging.debug("No callsign in spot; keys=%s", list(d.keys()))
        return None

    # Spotter / reporter alternates
    spotter = get_first(d, "spotter", "reporter", "deCallsign", "de", default="?")

    # Mode alternates (rarely differ, but be tolerant)
    mode = str(get_first(d, "mode", "opMode", "modulation", default="?")).strip() or "?"

    # Frequency alternates
    freq_val = get_first(d, "frequency", "freq", "frequencyMHz", "frequencyKhz")
    mhz = _parse_mhz(freq_val)
    freq_txt = f"{mhz:.3f} MHz" if mhz is not None else (str(freq_val) if freq_val is not None else "?")

    # Band (explicit or derived)
    band = extract_band(d)

    # Time alternates (prefer ISO/string, else epoch)
    t = get_first(d, "time", "timeISO", "timestamp")
    if isinstance(t, (int, float)):
        time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(float(t)))
    else:
        time_str = str(t) if t else "?"

    base = f"DX de {spotter}: **{callsign}** on {freq_txt} ({mode}) <t:{str(time.time()).split('.')[0]}:R>"

    # SOTA extras if present
    sota_fields = {"summitName", "summitRef", "summitPoints", "summitHeight"}
    if sota_fields.issubset(d.keys()):
        base = "SOTA " + base
        base += (
            f"\nSummit: {d['summitName']} — {d['summitRef']} — "
            f"a {d['summitPoints']}-point summit at {d['summitHeight']} m!"
        )

    return base, callsign, band, mode

# -------- Telnet loop (robust handshake) --------
def telnet_listener(host: str, port: int, username: str, password: str) -> None:
    """
    Connects, logs in, switches to JSON mode (tolerant of minor text changes), and streams spots.
    """
    with telnetlib.Telnet(host, port, timeout=30) as tn:
        logging.info("Connected to %s:%s", host, port)

        # Login prompts can vary a bit; keep it simple:
        tn.read_until(b"login:")
        tn.write((username + "\n").encode("utf-8"))
        tn.read_until(b"password:")
        tn.write((password + "\n").encode("utf-8"))

        initialized = False
        requested_json = False

        while True:
            raw = tn.read_until(b"\n", timeout=30)
            data = raw.decode("utf-8", errors="replace").strip("\r\n")
            if not data:
                # Idle keepalive—NOP usually fine. If it ever errors, ignore.
                try:
                    tn.write(telnetlib.IAC + telnetlib.NOP)
                    logging.debug("Sent Telnet NOP keepalive.")
                except Exception:
                    pass
                continue

            low = data.lower()
            logging.debug("Line: %s", data)

            # General HamAlert greeting / prompt detection
            if "hamalert" in low and "hello" in low:
                continue

            # Prompt often looks like "<user> de HamAlert >" but don't hard-match
            if ("de hamalert" in low or "hamalert >" in low) and not requested_json:
                logging.info("Setting JSON mode...")
                tn.write(b"set/json\n")
                requested_json = True
                continue

            # Success message may have punctuation/casing differences
            if "operation successful" in low:
                logging.info("JSON mode confirmed.")
                initialized = True
                continue

            if not initialized:
                # Ignore anything until JSON mode is confirmed
                continue

            # Parse JSON line
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

            msg, callsign, band, mode = built
            if not should_post(callsign, band, mode):
                continue

            if send_discord_webhook(msg):
                mark_posted(callsign, band, mode)

# -------- CLI / Main --------
def setup_args():
    p = argparse.ArgumentParser(description="HamAlert → Discord bridge (robust + per-band/mode de-dupe).")
    p.add_argument(
        "-l", "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level (default: INFO)",
    )
    p.add_argument(
        "--reconnect-delay",
        type=int,
        default=10,
        help="Seconds to wait before reconnecting after disconnect (default: 10)",
    )
    return p.parse_args()

def main():
    args = setup_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s | %(levelname)-8s | %(message)s",
    )

    missing = []
    if not HAMALERT_USERNAME or HAMALERT_USERNAME == "USERNAME":
        missing.append("HAMALERT_USERNAME")
    if not HAMALERT_PASSWORD or HAMALERT_PASSWORD == "PASSWORD":
        missing.append("HAMALERT_PASSWORD")
    if not DISCORD_WEBHOOK_URL or DISCORD_WEBHOOK_URL == "INSERT DISCORD WEBHOOK HERE":
        missing.append("DISCORD_WEBHOOK_URL")
    if missing:
        logging.warning("Missing/placeholder config for: %s", ", ".join(missing))

    # Simple reconnect loop (helps with transient disconnects)
    while True:
        try:
            telnet_listener(HAMALERT_HOST, HAMALERT_PORT, HAMALERT_USERNAME, HAMALERT_PASSWORD)
        except ConnectionRefusedError:
            logging.error("Telnet connection refused. Is the server reachable?")
        except Exception as e:
            logging.exception("Unhandled error: %s", e)

        logging.info("Reconnecting in %d seconds...", args.reconnect_delay)
        time.sleep(args.reconnect_delay)

if __name__ == "__main__":
    main()
