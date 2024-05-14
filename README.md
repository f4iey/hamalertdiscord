# HAM Alert Discord Integration
HamAlerts to Discord Webook Using Docker

## Hamalert Trigger
Before doing anything, connect to your hamalert account and create a trigger on https://hamalert.org and have it action "Telnet"

## Creating a discord webhook
To get the app running, you'll need to create a specific webhook and use a link.

To create a discord webhook follow the below instructions:
1. Server Settings
2. Integrations
3. Webooks
4. New Webhook
5. Change Name to anything you desire and set channel to where you want spots to output
6. Copy the URL to set `HAMALERT_WEBHOOK_URL` variable in the `Dockerfile`

## Build Image
To build the Docker image and get the app up and running, first edit the 3 environment varbaibles in the `Dockerfile` to match your hamalert credentials and your discord webhook integration.
```sh
git clone https://github.dev/f4iey/hamalertdiscord
docker build -t hamalert .
```
You can then run it with:
```sh
docker run hamalert
```
## Run with docker compose
Instead of this, you can also have these instructions in a new or existing compose file, replacing the environment variables, using the prebuilt image:
```yml
services:
  hamalert:
    container_name: hamalert
    image: ghcr.io/f4iey/hamalertdiscord:feature-dapnet
    environment:
      - HAMALERT_USERNAME=N0CALL
      - HAMALERT_PASSWORD=S53CRET
      - HAMALERT_WEBHOOK_URL=DS3ORD
      - DAPNET_ENABLE=0
      - DAPNET_USER=PA6ER
      - DAPNET_PASSWORD=CY4HER
```




----------------------------------------------------------------------------------------------------

Created by W2ORT, forked by F4IEY
