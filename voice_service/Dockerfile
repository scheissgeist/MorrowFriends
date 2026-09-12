FROM python:3.12-slim

WORKDIR /srv/morrowfriends
COPY voice_service/requirements.txt ./voice_service/requirements.txt
RUN pip install --no-cache-dir -r voice_service/requirements.txt

COPY app/__init__.py ./app/__init__.py
COPY app/voice.py ./app/voice.py
COPY voice_service ./voice_service

USER 65534:65534
EXPOSE 8080
CMD ["uvicorn", "voice_service.server:app_from_env", "--factory", "--host", "127.0.0.1", "--port", "8080", "--ws", "websockets-sansio", "--proxy-headers", "--forwarded-allow-ips=127.0.0.1"]
