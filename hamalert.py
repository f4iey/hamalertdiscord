import telnetlib
import json
import requests
import os
import time

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
        print("Discord webhook sent successfully.")
    else:
        print("Failed to send Discord webhook. Status code:", response.status_code)

def telnet_listener(host, port, username, password):
    try:
        with telnetlib.Telnet(host, port) as tn:
            tn.read_until(b"login: ")
            tn.write(username.encode("utf-8") + b"\n")
            tn.read_until(b"password: ")
            tn.write(password.encode("utf-8") + b"\n")

            while True:
                data = tn.read_until(b"\n").decode("utf-8").strip()
                print("Received data:", data)

                # Split the received data into separate pieces
                pieces = data.split()

                # Ensure that the data has enough pieces to extract relevant information
                if len(pieces) >= 5 and pieces[1] == "de":
                    source_call = pieces[2].strip(':')
                    destination_call = pieces[3]
                    frequency = pieces[4]
                    timestamp = pieces[-1]

                    # Construct the message for Discord webhook
                    message = f"DX de {source_call}: "
                    message += f"**{frequency}** on {destination_call} "
                    message += "<t:" + str(time.time()).split('.')[0] + ":R>"

                    send_discord_webhook(message)
                else:
                    print("Received data is not in the expected format. Skipping.")
                    print("Number of pieces:", len(pieces))
                    print("Received data:", pieces)

    except ConnectionRefusedError:
        print("Telnet connection refused. Make sure the server is running and reachable.")
    except Exception as e:
        print("An error occurred:", e)



if __name__ == "__main__":
    # HAM ALERT TELNET INFORMATION
    HOST = "hamalert.org"
    PORT = 7300
    if HAMALERT_USERNAME == "N0CALL" or HAMALERT_PASSWORD == "S53CRET" or DISCORD_WEBHOOK_URL == "DS3ORD":
        print("\033[91mERROR: You need to set envvars first!\033[0m")
        exit(1)
    telnet_listener(HOST, PORT, HAMALERT_USERNAME, HAMALERT_PASSWORD)
