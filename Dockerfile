FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        bc \
        ca-certificates \
        curl \
        dnsutils \
        iproute2 \
        jq \
        netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

COPY . /app
RUN chmod +x /app/ip.sh /app/server.py

EXPOSE 10000
CMD ["python", "/app/server.py"]
