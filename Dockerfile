FROM python:3.10

WORKDIR /usr/src/hamalert

COPY hamalert.py ./
COPY dapnet.py ./
RUN pip install --no-cache-dir requests
ENV HAMALERT_USERNAME="N0CALL"
ENV HAMALERT_PASSWORD="S53CRET"
ENV HAMALERT_WEBHOOK_URL="DS3ORD"
# DAPNET, disabled by default with 0
ENV DAPNET_ENABLE="0"
ENV DAPNET_USER="PA6ER"
ENV DAPNET_PASSWORD="CY4HER"

CMD [ "python", "./hamalert.py" ]
