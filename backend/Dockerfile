FROM python:3.12-slim

WORKDIR /app

# Client tools so Farmhand can mount NAS shares itself (Storage page): mount.cifs for SMB, mount.nfs for NFS.
RUN apt-get update \
 && apt-get install -y --no-install-recommends cifs-utils nfs-common \
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
ENV FARMHAND_PORT=5546
ENV FARMHAND_STORAGE_ROOT=/data/storage

EXPOSE 5546

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${FARMHAND_PORT:-5546}"]
