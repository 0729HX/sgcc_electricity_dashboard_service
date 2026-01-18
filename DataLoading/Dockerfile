FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 TZ=Asia/Shanghai PYTHON_IN_DOCKER=1

WORKDIR /app

COPY requirements.txt ./requirements.txt

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        firefox-esr \
        wget \
        ca-certificates \
        fonts-wqy-zenhei && \
    wget -O /tmp/geckodriver.tar.gz https://github.com/mozilla/geckodriver/releases/download/v0.34.0/geckodriver-v0.34.0-linux64.tar.gz && \
    tar -C /usr/bin -xzf /tmp/geckodriver.tar.gz && \
    chmod +x /usr/bin/geckodriver && \
    rm -f /tmp/geckodriver.tar.gz && \
    pip install --no-cache-dir -r requirements.txt && \
    rm -rf /var/lib/apt/lists/*

COPY . .

WORKDIR /app/DataLoading

CMD ["python", "main.py"]
