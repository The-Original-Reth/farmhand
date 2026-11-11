# Hello: an example Farmhand plugin

Hello shows each of the farm's printers and how far along its print is, read live from Farmhand's
[plugin API](../../docs/plugins.md). Its page updates by itself when a print starts, pauses or finishes, and takes
Farmhand's colours. It's small on purpose: copy this folder to start a plugin of your own.

It shows how to:

- serve the manifest (`GET /manifest`) and a health check (`GET /health`) Farmhand asks every 30 seconds
- read `FARMHAND_URL` and `FARMHAND_TOKEN`, and send the token with every call
- turn Farmhand's refusals (401 token, 403 permission, 429 too often) into plain words on the page
- keep working when Farmhand is down: the page says so and the plugin keeps retrying
- listen to Farmhand's server-sent events (`/events`) and pass changes on to its page
- serve a page that works inside Farmhand at `/plugins/hello/` (relative addresses) and in Farmhand's colours
- keep its own settings (which printers to show) in a Docker volume

It's plain Python 3 with only the standard library, so there's nothing to install.

| File | What it does |
|---|---|
| `farmhand-plugin.json` | The manifest: id, name, port, page in Farmhand's menu, permissions |
| `hello/config.py` | The environment variables, and the plugin's one setting (in `/data/settings.json`) |
| `hello/farmhand.py` | Calls to the plugin API, with each refusal in plain words |
| `hello/watcher.py` | Keeps a picture of the farm up to date: events, a refresh every 20 s, retrying |
| `hello/server.py` | The plugin's web server: `/manifest`, `/health`, the page, `api/status`, `api/events`, `api/settings` |
| `hello/page.html` | The page shown inside Farmhand |
| `tests/` | Tests against a stand-in plugin API (`tests/fake_farmhand.py`) |
| `Dockerfile` | The image |

## Build it

On the machine that will run it (Docker installed), from a copy of Farmhand's repository:

```bash
docker build -t farmhand-hello plugins/hello
```

## Run it

It can run on Farmhand's own machine or any other machine on the farm's network that can reach Farmhand's API port
(4545). Start it first without a token, so Farmhand can read its manifest:

```bash
docker run -d --name farmhand-hello --restart unless-stopped -p 8080:8080 -v farmhand-hello-data:/data farmhand-hello
```

- `-p 8080:8080`: Farmhand reaches the plugin at `http://<this machine's address>:8080`.
- `-v farmhand-hello-data:/data`: the plugin's own settings, kept when the container is replaced.
- `--restart unless-stopped`: it starts again by itself after a reboot or a crash.

## Add it to Farmhand

1. In Farmhand, open the **Plugins** page (in the menu, under Settings).
2. Under **Add a plugin**, type the plugin's address, e.g. `http://192.168.10.215:8080`.
3. Farmhand shows what Hello wants to read (your printers, what they're printing, Farmhand's colours). Say yes.
4. Farmhand shows the plugin's `FARMHAND_URL` and `FARMHAND_TOKEN` **once**. Start the container again with them:

```bash
docker rm -f farmhand-hello
docker run -d --name farmhand-hello --restart unless-stopped -p 8080:8080 -v farmhand-hello-data:/data \
  -e FARMHAND_URL=http://192.168.10.213:4545/plugin-api/v1 \
  -e FARMHAND_TOKEN=<the token Farmhand showed> \
  farmhand-hello
```

**Hello** is now in Farmhand's menu. Its page is also at `http://<farmhand>:3636/plugins/hello/`, and straight on the
plugin at `http://<this machine>:8080/` (handy while you work on it).

If the page says Farmhand refused the token, make a new one on the Plugins page and start the container again with it.
By default Farmhand takes the token only from the plugin's address, so run the container on the machine you added it by.

## Run it without Docker, and run its tests

```bash
cd plugins/hello
FARMHAND_URL=http://192.168.10.213:4545/plugin-api/v1 FARMHAND_TOKEN=<token> HELLO_DATA=./data python -m hello
```

```bash
cd plugins/hello
pip install -r requirements-dev.txt
python -m pytest -q
```

The tests run the plugin against `tests/fake_farmhand.py`, a stand-in for the plugin API, so no Farmhand is needed.
They're separate from Farmhand's own tests.

## Make it your own

1. **Copy the folder**: `plugins/hello` to wherever your plugin will live (its own repository is fine).
2. **Rename it.** In `farmhand-plugin.json` set `id` (lower-case letters, digits and dashes; it becomes
   `/plugins/<id>/` in Farmhand), `name`, `version`, `author` and `homepage`, and the menu label and icon under
   `page` (`video`, `camera`, `chart`, `bell` or `dashboard`). Rename the `hello` Python package, `HELLO_DATA`, and
   the image and container names in the commands above.
3. **Ask for what you need, and nothing more.** List the permissions in `permissions`; the operator sees each in
   plain words before saying yes, and can untick any. The ones there are (see [docs/plugins.md](../../docs/plugins.md)):
   `printers:read`, `cameras:read`, `prints:read`, `farm:read`. To use one, add it to the manifest and call its
   endpoint from `hello/farmhand.py`, as `printers()` and `print_of()` do. A plugin already added keeps the permissions
   it was given: remove it on the Plugins page and add it again to ask for more.
4. **Change what it shows**: `watcher.py` decides what to ask Farmhand and keeps the result; `page.html` draws it.
5. **Keep the rules that make it work inside Farmhand**:
   - relative addresses in your page (`api/status`, never `/api/status`), since it's shown at `/plugins/<id>/`
   - server-sent events or asking now and then, not websockets (Farmhand doesn't pass websockets on)
   - the token stays in the plugin: the page asks the plugin, and only the plugin asks Farmhand
   - your own settings in your own volume: the plugin API is read-only, and Farmhand's files aren't yours
   - `/health` answers 2xx while you're well, and a short plain reason otherwise (shown on the Plugins page)
6. **Run its tests**, change them with it, and publish the image (e.g. on GitHub's container registry) so others can
   `docker run` it.
