# HAM Alert Discord Integration
HamAlerts to Discord Webhook with optional DAPNET delivery.

## HamAlert trigger
Create a trigger in your [HamAlert account](https://hamalert.org) and set its action to **Telnet**.

## Discord webhook
Create a Discord webhook under **Server Settings → Integrations → Webhooks**, then copy its URL for `DISCORD_WEBHOOK_URL`.

## Run with Docker Compose
Copy `docker-compose.yml.sample` to `docker-compose.yml` and replace the example values with your credentials and webhook URL. DAPNET delivery is disabled by default; set `DAPNET_ENABLE=1` to enable it and provide your DAPNET account credentials.

```yaml
services:
  hamalert:
    container_name: hamalert
    build: .
    environment:
      - HAMALERT_HOST=hamalert.org
      - HAMALERT_PORT=7300
      - HAMALERT_USERNAME=N0CALL
      - HAMALERT_PASSWORD=S53CRET
      - DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/your-webhook
      - DAPNET_ENABLE=0
      - DAPNET_USER=PA6ER
      - DAPNET_PASSWORD=CY4HER
```

Build and start the service with:

```sh
docker compose up --build -d
```

To enable DAPNET, change `DAPNET_ENABLE` to `1`. The DAPNET account configured by `DAPNET_USER` and `DAPNET_PASSWORD` is used for authentication and as the destination callsign.

## Run directly with Python
Install `requests`, set the same environment variables shown above, then run:

```sh
python hamalert.py
```

Created by W2ORT, forked by F4IEY.
Matthew O.
https://w2ort.com

Updated and heavily corrected by:
Dylon N6MX
Devin KN6PHZ

Special Thanks to:
Mark KD7DTS and the W6TRW Club!
