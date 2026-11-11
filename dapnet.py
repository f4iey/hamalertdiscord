"""Small client for the DAPNET calls API."""
import logging

import requests

DAPNET_CALLS_URL = "http://www.hampager.de:8080/calls"


def send(user, password, data, dest_call):
    """Send a text message to a DAPNET callsign. Return True on success."""
    payload = {
        "text": f"{user.upper()}: {data}",
        "callSignNames": [dest_call.lower()],
        "transmitterGroupNames": ["all"],
        "emergency": False,
    }
    try:
        response = requests.post(
            DAPNET_CALLS_URL,
            json=payload,
            auth=(user, password),
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        logging.error("DAPNET call request failed: %s", error)
        return False
    logging.info("DAPNET call sent (status %s).", response.status_code)
    return True


def get(user, password):
    """Return the latest call text for a DAPNET account, if available."""
    response = requests.get(
        DAPNET_CALLS_URL,
        params={"ownerName": user.lower()},
        auth=(user, password),
        timeout=10,
    )
    response.raise_for_status()
    calls = response.json()
    return calls[-1]["text"] if calls else None
