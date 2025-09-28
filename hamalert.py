import argparse
import telnetlib
import time
import json
import requests
import logging
import os

# Replace with your HamAlert username and password
HAMALERT_USERNAME = os.getenv('HAMALERT_USERNAME', 'N0CALL')
HAMALERT_PASSWORD = os.getenv('HAMALERT_PASSWORD', 'S53CRET')

# Replace with your Discord webhook URL
DISCORD_WEBHOOK_URL = os.getenv('HAMALERT_WEBHOOK_URL', 'DS3ORD')

def send_discord_webhook(content):
    data = {"content": content}
    headers = {"Content-Type": "application/json"}
    response = requests.post(DISCORD_WEBHOOK_URL, json=data, headers=headers)
    if response.status_code == 204:
        logging.info("Discord webhook sent successfully.")
    else:
        logging.error("Failed to send Discord webhook. Status code:", response.status_code)

def telnet_listener(host, port, username, password):
    try:
        with telnetlib.Telnet(host, port) as tn:
            tn.read_until(b"login: ")
            tn.write(username.encode("utf-8") + b"\n")
            tn.read_until(b"password: ")
            tn.write(password.encode("utf-8") + b"\n")
            initialized = False

            while True:
                data = tn.read_until(b"\n", timeout=30).decode("utf-8").strip()
                if data != "":
                    logging.info(f"Received data: {data}")

                if data == f"Hello {username}, this is HamAlert":
                    continue
                if data == f"{username} de HamAlert >":
                    logging.info("Telnet connected, attempting to set JSON mode.")
                    time.sleep(1)
                    tn.write(b"set/json\n")
                    continue
                if data == "Operation successful":
                    logging.info("Successfully set JSON mode")
                    initialized = True
                    continue
                if not initialized:
                    # Dont try to parse incoming data until finished setting up JSON mode.
                    # It's possible a spot comes in right when we first connect which can't be parsed.
                    continue

                if data == "":
                    # We must have hit the timeout case in the read.
                    # Just send a keepalive command and try another read.
                    logging.debug(f"10s timeout hit, sending no-op")
                    tn.sock.sendall(telnetlib.IAC + telnetlib.NOP)
                    continue

                # Split the received data into json object
                try:
                    data_dict = json.loads(data)

                    required_fields = {'fullCallsign', 'callsign', 'frequency', 'mode', 'spotter', 'time', 'source'}
                    # Ensure that the data has enough pieces to extract relevant information
                    if all(key in data_dict for key in required_fields):
                        # Construct the message for Discord webhook
                        message = f"DX de {data_dict['spotter']}: **{data_dict['fullCallsign']}** on {data_dict['frequency']} ({data_dict['mode']}) <t:{str(time.time()).split('.')[0]}:R>"
                        sota_fields = {'summitName', 'summitRef', 'summitPoints', 'summitHeight'}
                        if all(key in data_dict for key in sota_fields):
                            message = "SOTA " + message
                            message += f"\nSummit: {data_dict['summitName']} -- {data_dict['summitRef']} -- a {data_dict['summitPoints']} point summit at {data_dict['summitHeight']}m elevation!"

                    else:
                        logging.warning("Received data is not in the expected format. Skipping.")
                        logging.warning(f"Parsed data: {data_dict}")

                except json.JSONDecodeError as e:
                    resetJson = True
                    message = data

                logging.info(f"sending message to discord: {message}")
                send_discord_webhook(message)

    except ConnectionRefusedError:
        logging.error("Telnet connection refused. Make sure the server is running and reachable.")
    except Exception as e:
        logging.error("An error occurred: %s", str(e))

def setup_args():
    # Create an argument parser
    parser = argparse.ArgumentParser()

    # Add an argument for the logging level
    parser.add_argument('-l', '--log-level', help='The logging level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'])

    # Parse the arguments
    args = parser.parse_args()

    # Set the logging level
    logging.basicConfig(level=args.log_level)

if __name__ == "__main__":
    # HAM ALERT TELNET INFORMATION
    HOST = "hamalert.org"
    PORT = 7300

    setup_args()
    if HAMALERT_USERNAME == "N0CALL" or HAMALERT_PASSWORD == "S53CRET" or DISCORD_WEBHOOK_URL == "DS3ORD":
        print("\033[91mERROR: You need to set envvars first!\033[0m")
        exit(1)
    telnet_listener(HOST, PORT, HAMALERT_USERNAME, HAMALERT_PASSWORD)
