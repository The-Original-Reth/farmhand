"""
What the plugin is told when its container starts (environment variables). Farmhand gives every plugin two, shown to
the operator once when they add it on Farmhand's Plugins page:

    FARMHAND_URL    where the plugin API is, e.g. http://192.168.10.213:4545/plugin-api/v1
    FARMHAND_TOKEN  this plugin's token, sent with every call

The rest are this plugin's own:

    PORT                     where it listens (8080, as farmhand-plugin.json says)
    STREAM_DATA              its own settings, stream key, YouTube sign-in, saved layouts and what was last live:
                             /data, a Docker volume of its own, so they outlive the container
    STREAM_FOLDER            the stream folder (pictures, slideshows, music): /media, a folder the operator mounts in
                             (a bind mount, or a NAS share mounted on the plugin's machine)
    STREAM_FOLDER_SHOWN_AS   optional: the same folder as people reach it over the network (a Windows share path,
                             say), shown on the page so they know where to copy pictures and music in by hand
    STREAM_TEST_DESTINATION  optional, for trying the plugin out: an rtmp:// address that takes the stream instead
                             of YouTube (the stream key pasted on the page goes on its end). While it's set, YouTube
                             is never sent anything, signed in or not
    FARMHAND_STREAM_ENCODER  auto (the default: an NVIDIA card's encoder when one works, else the processor),
                             nvenc or cpu
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    farmhand_url: str = ""
    farmhand_token: str = ""
    port: int = 8080
    data_dir: Path = Path("/data")
    media_dir: Path = Path("/media")
    media_shown_as: str | None = None
    test_destination: str | None = None

    @classmethod
    def from_env(cls, env=os.environ) -> "Config":
        return cls(
            farmhand_url=env.get("FARMHAND_URL", "").strip().rstrip("/"),
            farmhand_token=env.get("FARMHAND_TOKEN", "").strip(),
            port=int(env.get("PORT", "8080")),
            data_dir=Path(env.get("STREAM_DATA", "/data")),
            media_dir=Path(env.get("STREAM_FOLDER", "/media")),
            media_shown_as=(env.get("STREAM_FOLDER_SHOWN_AS") or "").strip() or None,
            test_destination=(env.get("STREAM_TEST_DESTINATION") or "").strip().rstrip("/") or None,
        )


# The one the plugin runs with (__main__ reads it from the environment; tests set their own)
settings = Config.from_env()
