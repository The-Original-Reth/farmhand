FROM python:3.12-slim

WORKDIR /app

# Client tools so Farmhand can mount NAS shares itself (Storage page): mount.cifs for SMB, mount.nfs for NFS.
# And the libraries gmsh needs to load (it draws a project's STEP / IGES previews; it never opens a window). On ARM
# there's no gmsh to install (see requirements.txt), and these are just unused.
# openssh-client: ssh / scp to a printer's Pi, for what Moonraker won't do over HTTP (copying its database file into
# backups and back, writing mainsail.cfg where it really is): see app/services/printer_ssh.py.
# No ffmpeg: sending the stream to YouTube or Twitch is the stream plugins' job, in their own containers. The fonts are
# the ones the stream's words can be written in (the stream plugins install the same), so Stream control's page shows
# them as the stream will (app/services/stream_control/fonts.py).
RUN apt-get update \
 && apt-get install -y --no-install-recommends cifs-utils nfs-common openssh-client \
    libgomp1 libglu1-mesa libgl1 libxcursor1 libxft2 libxinerama1 libxrender1 \
    fonts-dejavu-core fonts-liberation fonts-roboto-unhinted fonts-open-sans fonts-lato fonts-montserrat fonts-bebas-neue \
    fonts-comic-neue fonts-firacode \
 && rm -rf /var/lib/apt/lists/*

# psycopg[binary] avoids needing libpq-dev at build time; keep this minimal.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY tests ./tests
COPY seed_data ./seed_data
COPY pyproject.toml .

# Overridable at runtime via FARMHAND_PORT (docker-compose sets this).
ENV FARMHAND_HOST=0.0.0.0
ENV FARMHAND_PORT=4545
ENV FARMHAND_STORAGE_ROOT=/data/storage

EXPOSE 4545

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${FARMHAND_PORT:-4545}"]
