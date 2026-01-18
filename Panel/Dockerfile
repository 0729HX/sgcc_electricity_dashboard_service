FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt Flask

COPY . .

WORKDIR /app/Panel

ENV PYTHONUNBUFFERED=1 TZ=Asia/Shanghai

CMD ["python", "app.py"]
