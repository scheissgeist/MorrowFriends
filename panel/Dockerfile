FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py coop_rules.py players.py ./
COPY templates ./templates

# TES3MP_ROOT is bind-mounted at runtime so the panel edits the live server's
# config.lua and player records. PANEL_PASS has no default on purpose: app.py
# refuses every login when it is unset, so a misconfigured deploy locks the
# panel instead of leaving it open.
ENV TES3MP_ROOT=/tes3mp \
    PANEL_PORT=8091 \
    PANEL_USER=admin

EXPOSE 8091

CMD ["gunicorn", "--bind", "0.0.0.0:8091", "--workers", "2", "--timeout", "30", "app:app"]
