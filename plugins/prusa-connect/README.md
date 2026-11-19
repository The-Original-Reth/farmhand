# Prusa Connect plugin

Farmhand's Prusa printers connected through the farm's own **Prusa Connect** server (Prusa's self-hosted printer
server, [prusa3d/prusa-connect](https://github.com/prusa3d/prusa-connect)) instead of each printer's PrusaLink.

Once the plugin is added, **Prusa Connect** is a third **Connection** choice for a printer, beside Mainsail and
PrusaLink. For each printer connected this way, Farmhand takes its state, temperatures and current print from Prusa
Connect (on the printer's page, on Monitor, for other plugins' events, and for the print history Farmhand records), and
a print sent to it from Farmhand goes through Prusa Connect, which starts it. Farmhand asks its PrusaLink only to read the
start of each printed file for its filament price (read only, given the PrusaLink password), since Prusa Connect can't
read files on the printer.

Built on Prusa Connect by Prusa Research. The plugin only calls Prusa Connect's REST API; none of its code is used here.
Prusa Connect is a public beta (0.x), so its API can still change from one release to the next.

## Before you start

- A Prusa Connect server on the farm's network, set up (its first-run wizard done), with your Prusa printers paired
  with it. **A Prusa printer can be paired with one Connect server at a time**: pairing it with your own takes it off
  Prusa's cloud Connect (connect.prusa3d.com). Its PrusaLink is unaffected.
- Farmhand with the `printers:report` permission (this version or later).

## Run it

On any machine that reaches both Farmhand and Prusa Connect (beside Prusa Connect is simplest):

```bash
sudo mkdir -p /opt/farmhand-prusa-connect
cd /opt/farmhand-prusa-connect
sudo curl -fsSLO https://raw.githubusercontent.com/The-Original-Reth/farmhand/main/plugins/prusa-connect/docker-compose.yml
sudo docker compose up -d --build
```

Farmhand's Plugins page has the same steps under **Run a plugin in its own container** (choose Prusa Connect).

1. **Add it** on Farmhand's Plugins page at `http://<that machine>:8085`. It asks to see your printers
   (`printers:read`), to report your Prusa printers' status (`printers:report`) and to start the prints you send them
   (`printers:print`).
2. **Give it its token**: put the two lines Farmhand shows (`FARMHAND_URL=...`, `FARMHAND_TOKEN=...`) in
   `prusa-connect.env` beside the compose file, then `sudo docker compose up -d --force-recreate`.
3. **Pair it with Prusa Connect**: open **Prusa Connect** in Farmhand's menu, type Prusa Connect's address (e.g.
   `http://192.168.10.93:8080`) and press **Pair with Prusa Connect**. It shows a short code: open Prusa Connect (the
   link beside it), sign in, and approve it. The plugin gets a token that can read the printers and start prints
   ("read" and "operate"); nobody types a password.
   Prusa Connect lists it under Settings, API credentials, where it can be revoked. Tokens last 90 days: pair again
   when the page says Prusa Connect refused it.
   A Prusa Connect set up in **open mode** (no sign-in) has nobody to approve a code, and needs none: the page says so
   and the plugin reads it without pairing.
4. **Say which printer is which**: on the plugin's page, choose the Prusa Connect printer for each Farmhand Prusa
   printer. One with the same name on both sides is chosen by itself.
5. **Connect the printers through it**: in Farmhand, edit each printer and set **Connection** to **Prusa Connect**.
   Set it back to **PrusaLink** any time; nothing is lost either way.

## How it works

**Beyond PrusaLink**: each report also carries what Prusa Connect knows that PrusaLink doesn't: the loaded material,
the nozzle (size, hardened, high flow), the chamber temperature, fans, speed and flow, and a message on the printer's
screen. Farmhand shows them on the printer's page. It also carries the extruder's odometer, from which Farmhand measures
each new print's filament (instead of the slicer's estimate), the printer's lifetime "Filament used", and filament
maintenance reminders; prints recorded before keep their figures.

**Sending a print**: Farmhand POSTs a one-time ticket to the plugin's `/farmhand/print`. The plugin fetches the G-code
from Farmhand with it, puts it in Prusa Connect's storage as a temporary copy, and asks Prusa Connect to send it to the
printer's USB stick (replacing a file of that name) and start it. A printer that isn't ready, or isn't linked yet, is
refused with the reason, which Farmhand shows.


Every 10 seconds the plugin asks Prusa Connect for its printers and sends Farmhand a report of each printer switched
to it (`PUT /plugin-api/v1/printers/{id}/status`, see [docs/plugins.md](../../docs/plugins.md)), also while nothing
changes. A printer Prusa Connect isn't hearing from, or one not linked yet, is reported unreachable with the reason,
which Farmhand shows as the printer's. If the plugin stops, Farmhand shows its printers as unreachable after two
minutes, saying the plugin hasn't reported.

Its settings (Prusa Connect's address, its token, which printer is which) are in `/data/settings.json`, a Docker volume.
`PRUSA_CONNECT_URL` in its env file sets the address to start with.

## Tests

```bash
cd plugins/prusa-connect
python -m pytest -q
```

They run against stand-ins for Farmhand and Prusa Connect (`tests/fakes.py`), and need only Python 3.11+ and pytest.
