# The Stream plugin: build with  docker build -t farmhand-stream plugins/stream
# Its page is a small Vite build (page/), made in the first stage; the plugin itself is Python with ffmpeg and fonts.
FROM node:22-alpine AS page
WORKDIR /page
COPY page/package.json page/package-lock.json ./
RUN npm ci
COPY page/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app

# ffmpeg reads the cameras and makes the stream; the fonts are the ones a square's words can be written in
# (live_stream/fonts.py FONTS). Debian's ffmpeg can use an NVIDIA card's encoder (NVENC) when the container is given
# the card and its driver's libraries (see README); it falls back to the processor otherwise.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core \
    fonts-liberation fonts-roboto-unhinted fonts-open-sans fonts-lato fonts-montserrat fonts-bebas-neue fonts-comic-neue fonts-firacode \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY streamer/ ./streamer/
COPY --from=page /streamer/web/ ./streamer/web/
# Farmhand's plugin contract: the manifest is in the image at /farmhand-plugin.json (and served at GET /manifest)
COPY farmhand-plugin.json /farmhand-plugin.json

# FARMHAND_URL and FARMHAND_TOKEN are given with docker run (-e or --env-file), never baked into the image
ENV PORT=8080 \
    STREAM_DATA=/data \
    STREAM_FOLDER=/media \
    PYTHONUNBUFFERED=1
# Its settings, stream key, YouTube sign-in and layouts: a volume of its own, so they outlive the container
VOLUME /data
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/manifest', timeout=4)"

CMD ["python", "-m", "streamer"]
