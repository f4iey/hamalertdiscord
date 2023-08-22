FROM python:3

WORKDIR /usr/src/hamalert

COPY hamalert.py ./
RUN pip install --no-cache-dir requests
ENV HAMALERT_USERNAME="N0CALL"
ENV HAMALERT_PASSWORD="S53CRET"
ENV HAMALERT_WEBHOOK_URL="DS3ORD"

CMD [ "python", "./hamalert.py" ]
