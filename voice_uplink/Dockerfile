FROM python:3.12-slim

WORKDIR /uplink

# Pin to the version the launcher runs. websockets 14.x sync client does
# not accept ping_interval, so a <15 cap made every connection fail.
RUN pip install --no-cache-dir "websockets==15.0.1"

# The launcher's own relay bridge, reused verbatim so the wire protocol cannot
# drift between the Windows host path and this Linux service.
COPY app ./app
COPY uplink.py ./

# CoreScripts writes its JSON one level below the server data mount.
ENV TES3MP_DATA=/server/data/data \
    PYTHONUNBUFFERED=1

CMD ["python", "uplink.py"]
