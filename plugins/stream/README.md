# YouTube Stream: the live stream to YouTube as a Farmhand plugin

The YouTube Stream plugin (id `stream`) sends printers' cameras live to **YouTube Live**, no OBS needed, from a container of its own, so a
Farmhand update, restart or crash never stops the stream. It is the only way Farmhand streams: Farmhand's own Stream
page is gone. Once the plugin is added, **YouTube** is in Farmhand's menu where that page was, after Monitor, and opens
the plugin's page inside Farmhand (`/plugin/stream`; an old `/stream` bookmark leads there too), in Farmhand's colours.
It works as the Stream page always did: the grid
of squares, cards with pictures, slideshows and words, the music, the words under the cameras, taking turns, the
resolution, the delay, saved layouts, YouTube sign-in and broadcasts, or a pasted stream key.

What it adds over the Stream page older Farmhands had built in:

- **Each camera is read on its own.** A camera that stops shows **Camera down** with the printer's name, in the
  square's background colour and the chosen font and colour, and goes back to live video by itself; the other cameras
  and the connection to YouTube carry on. Going live with a camera off works, and the page lists each camera as live
  or down while live.
- **The preview before going live** shows each camera's snapshot, as the plugin fetches it (the page never talks to
  the cameras). A camera with no snapshot address, or one that doesn't answer (an RTSP camera, or one moved to go2rtc
  that Mainsail still lists an old snapshot address for), shows a frame taken from its video every few seconds.
- **It goes live again by itself** after its own restart (a reboot, a power cut, a new image), if it was live, on the
  same YouTube broadcast: a restart leaves the broadcast live, and only Stop ends it.
  While its delay fills again, YouTube is shown a **holding screen** (its words, picture, colours and font are set on the
  Stream page), so the broadcast keeps getting video; then it switches to the cameras with the whole delay in place.
- **Farmhand going down doesn't stop it.** The cameras are read at the addresses last heard of, and the words under
  them become just the printers' names until Farmhand is back.
- **It reads only what it needs**: the cameras' addresses (`cameras:read`) and what each printer is printing
  (`prints:read`). It has no database: its settings, stream key, YouTube sign-in and saved layouts are in its own
  volume (`/data/settings.json`, readable only by the plugin), and its API never answers the key or the sign-in.
- **Moving over from the old Stream page**: with `stream:migrate`, the first time it starts it brings over, once, what
  a Farmhand from before Stream became a plugin had set up on its Stream page: settings, saved layouts, stream key and
  YouTube sign-in. Farmhand keeps its copy in its database, unused.

| Path | What it is |
|---|---|
| `farmhand-plugin.json` | The manifest: id `stream`, port 8080, a page in Farmhand's menu, its permissions |
| `streamer/live_stream/` | The engine (first copied from Farmhand's own, now gone); `feeders.py` reads each camera and draws the "Camera down" square |
| `streamer/stream_media.py`, `youtube_live.py`, `routes.py` | The stream folder, YouTube sign-in and the page's API |
| `streamer/store.py`, `farm.py`, `migrate.py`, `layouts.py`, `app.py` | The plugin's own: its settings file, reading Farmhand, the one-off move, saved layouts, the web server |
| `page/` | The page (first copied from Farmhand's own Stream page), a small Vite build of its own (`npm run build` puts it in `streamer/web/`) |
| `tests/` | Tests against stand-ins for Farmhand's plugin API and ffmpeg (`python -m pytest -q`) |

## Build it

On the machine that will run it (Docker installed), from a copy of Farmhand's repository:

```bash
docker build -t farmhand-stream plugins/stream
```

## The stream folder

The stream's pictures, slideshows and music are files in a folder you give the container at `/media` (`images/`,
`slideshows/<name>/`, `music/`; the plugin makes them). Moving over from Farmhand's old Stream page, give it the same
stream folder that page used (usually `stream` beside the STL folder on the NAS; the move from Farmhand says where, if
one was chosen), so the squares find their pictures:

- **A folder on the plugin's machine**: `-v /opt/farmhand-stream/media:/media`.
- **A NAS share**: mount it on the plugin's machine (in `/etc/fstab`, e.g. `//nas/3d_Printing_Elves/Farmhand/stream
  /mnt/stream cifs credentials=/root/.nas,uid=0,gid=0,iocharset=utf8 0 0`, or NFS), then `-v /mnt/stream:/media`.
  Docker can also mount it itself with a `cifs` volume (see the compose example below).

Pictures added on the page are written there; ones copied in by hand count too (press **Resync**). Set
`STREAM_FOLDER_SHOWN_AS` to the folder as people reach it over the network (e.g. `\\nas\3d_Printing_Elves\Farmhand\stream`)
and the page shows it, for copying files in by hand.

## Run it

It runs on Farmhand's machine or any other machine on the farm's network that reaches Farmhand's API port (4545) and the
cameras. [`docker-compose.yml`](docker-compose.yml) here is ready to use: it builds the plugin straight from this repository
on GitHub (git must be installed), restarts it by itself, keeps its settings in a volume and reads `stream.env` once
Farmhand gives the token. Farmhand's Plugins page shows the same file and these steps under **Run a plugin in its own
container**, with Stream chosen (a copy in `frontend/src/plugins/compose/stream.yml`; `tests/test_compose.py` checks the
two match).

```bash
sudo mkdir -p /opt/farmhand-stream && cd /opt/farmhand-stream
sudo curl -fsSLo docker-compose.yml https://raw.githubusercontent.com/The-Original-Reth/farmhand/main/plugins/stream/docker-compose.yml
sudo docker compose up -d --build
```

Change `./media` in it to the stream folder (see above) first. Built from a copy of the repository instead
(`docker build -t farmhand-stream plugins/stream`), remove its `build:` line.

### An NVIDIA card

ffmpeg compresses the stream on an NVIDIA card (NVENC) when the container can reach it, leaving the processor to read
the cameras and lay out the grid; otherwise it uses the processor (the page says which while live). The machine needs
the NVIDIA driver's user-space libraries matching the driver in use (on an LXC container under Proxmox, the host's:
e.g. `libnvidia-encode-580`, `nvidia-utils-580`, `libnvidia-compute-580` and `libnvidia-decode-580` at the host's
version, held with `apt-mark hold`), and the container is given the card and the libraries ffmpeg loads:

```yaml
    devices:
      - /dev/nvidia0
      - /dev/nvidiactl
      - /dev/nvidia-uvm
      - /dev/nvidia-uvm-tools
    volumes:
      - /usr/lib/x86_64-linux-gnu/libcuda.so.1:/usr/lib/x86_64-linux-gnu/libcuda.so.1:ro
      - /usr/lib/x86_64-linux-gnu/libnvidia-encode.so.1:/usr/lib/x86_64-linux-gnu/libnvidia-encode.so.1:ro
      - /usr/lib/x86_64-linux-gnu/libnvcuvid.so.1:/usr/lib/x86_64-linux-gnu/libnvcuvid.so.1:ro
```

`FARMHAND_STREAM_ENCODER` (`auto`, `nvenc` or `cpu`) says which to use; `auto` (the default) tries the card.

On a Proxmox LXC container, with the NVIDIA driver already on the host, share the card into the container first: add
to `/etc/pve/lxc/<id>.conf` on the host, then restart the container (`ls -l /dev/nvidia*` on the host shows the numbers
after `c`; these are the usual ones):

```
lxc.cgroup2.devices.allow: c 195:* rwm
lxc.cgroup2.devices.allow: c 234:* rwm
lxc.cgroup2.devices.allow: c 238:* rwm
lxc.mount.entry: /dev/nvidia0 dev/nvidia0 none bind,optional,create=file
lxc.mount.entry: /dev/nvidiactl dev/nvidiactl none bind,optional,create=file
lxc.mount.entry: /dev/nvidia-modeset dev/nvidia-modeset none bind,optional,create=file
lxc.mount.entry: /dev/nvidia-uvm dev/nvidia-uvm none bind,optional,create=file
lxc.mount.entry: /dev/nvidia-uvm-tools dev/nvidia-uvm-tools none bind,optional,create=file
```

Then, in the container, install NVIDIA's libraries at **exactly** the host's driver version (`nvidia-smi` on the host
says it) and hold them there, so an update can't move them away from it:

```bash
sudo apt install --no-install-recommends libnvidia-encode-580=<version> nvidia-utils-580=<version>
sudo apt-mark hold libnvidia-encode-580 nvidia-utils-580 libnvidia-compute-580 libnvidia-decode-580
```

`nvidia-smi` in the container should then show the card. When the host's driver is updated, update the container's
libraries to the same version (until then the stream quietly goes back to the processor).

## Add it to Farmhand

1. In Farmhand, open the **Plugins** page (in the menu, under Settings).
2. Under **Add a plugin**, type its address, e.g. `http://192.168.10.215:8080`.
3. Farmhand shows what Stream wants: your printers' cameras, what they're printing, and (once) the old Stream page's
   set-up. Untick **stream:migrate** to start afresh instead. Say yes.
4. Farmhand shows `FARMHAND_URL` and `FARMHAND_TOKEN` **once**. Put them in `stream.env`:

   ```
   FARMHAND_URL=http://192.168.10.213:4545/plugin-api/v1
   FARMHAND_TOKEN=...
   ```

   and start it again: `docker compose up -d --force-recreate`.

**Stream** appears in Farmhand's menu, after Monitor. The first time it starts with `stream:migrate`, it brings the old
Stream page's set-up over (or press **Bring over Farmhand's Stream settings** on its page).

## Trying it out without YouTube

Set `STREAM_TEST_DESTINATION` to an RTMP receiver, e.g. [MediaMTX](https://github.com/bluenviron/mediamtx)
(`docker run -d --name mediamtx -p 1935:1935 -p 8554:8554 bluenviron/mediamtx:1.9.3`):

```
STREAM_TEST_DESTINATION=rtmp://192.168.10.215:1935/live
```

Paste any stream key on the page (e.g. `farmtest`): the stream goes to `rtmp://192.168.10.215:1935/live/farmtest`, and
YouTube is never sent anything, signed in or not. Watch it with `ffplay rtsp://192.168.10.215:8554/live/farmtest`, or
save a few seconds with `ffmpeg -i rtsp://192.168.10.215:8554/live/farmtest -t 10 -c copy test.mp4`.

## Settings (environment variables)

| Variable | What it is |
|---|---|
| `FARMHAND_URL`, `FARMHAND_TOKEN` | Where Farmhand's plugin API is, and this plugin's token (from the Plugins page) |
| `PORT` | Where it listens (8080) |
| `STREAM_DATA` | Its settings folder (`/data`: a volume) |
| `STREAM_FOLDER` | The stream folder (`/media`: a mount) |
| `STREAM_FOLDER_SHOWN_AS` | Optional: the stream folder as people reach it over the network, shown on the page |
| `STREAM_TEST_DESTINATION` | Optional: an `rtmp://` address the stream goes to instead of YouTube |
| `FARMHAND_STREAM_ENCODER` | `auto` (default), `nvenc` or `cpu` |

## Developing

```bash
cd plugins/stream && pip install -r requirements-dev.txt && python -m pytest -q
cd plugins/stream/page && npm install && npm run build     # the page, into streamer/web
STREAM_DATA=./data STREAM_FOLDER=./media python -m streamer  # the plugin on :8080 (ffmpeg on the PATH to go live)
cd plugins/stream/page && npm run dev                      # the page on :3638, its API passed to :8080
```

Much of the code began as Farmhand's own Stream page, copied (the first commit adding this folder copies it unchanged).
That page is gone from Farmhand now, so this folder is the only copy.
