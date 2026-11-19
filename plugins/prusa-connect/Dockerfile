# Farmhand's Prusa Connect plugin: build with  docker build -t farmhand-prusa-connect plugins/prusa-connect
# Only Python's standard library is used, so there's nothing to pip install.
FROM python:3.12-slim

WORKDIR /app
COPY prusa_connect/ ./prusa_connect/
# Farmhand's plugin contract: the manifest is in the image at /farmhand-plugin.json (and served at GET /manifest)
COPY farmhand-plugin.json /farmhand-plugin.json

# FARMHAND_URL and FARMHAND_TOKEN come from its env file (Farmhand's Plugins page), never baked into the image
ENV PORT=8085 \
    PRUSA_CONNECT_DATA=/data \
    PYTHONUNBUFFERED=1
# Its settings (Prusa Connect's address, its token, which printer is which) live here: a volume, so they outlive the container
VOLUME /data
EXPOSE 8085

HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8085/manifest', timeout=4)"

CMD ["python", "-m", "prusa_connect"]
