#!/bin/sh
# Bring this Farmhand up to date in one go: the newest code from GitHub, then every part of it (database, server,
# web page, camera relay) rebuilt where it changed and started together, so a part added later is never left out.
# Your data is kept in the Docker volumes. Run it from anywhere:  sudo sh update.sh
set -e
cd "$(dirname "$0")"
git pull
docker compose up -d --build --remove-orphans
docker compose ps
