# The Hello plugin: build with  docker build -t farmhand-hello plugins/hello
# Only Python's standard library is used, so there's nothing to pip install.
FROM python:3.12-slim

WORKDIR /app
COPY hello/ ./hello/
# Farmhand's plugin contract: the manifest is in the image at /farmhand-plugin.json (and served at GET /manifest)
COPY farmhand-plugin.json /farmhand-plugin.json

# FARMHAND_URL and FARMHAND_TOKEN are given with docker run (-e), never baked into the image
ENV PORT=8080 \
    HELLO_DATA=/data \
    PYTHONUNBUFFERED=1
# The plugin's own settings live here: mount a volume so they outlive the container
VOLUME /data
EXPOSE 8080

# Docker's own check, separate from Farmhand's (which asks /health every 30 s)
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/manifest', timeout=4)"

CMD ["python", "-m", "hello"]
