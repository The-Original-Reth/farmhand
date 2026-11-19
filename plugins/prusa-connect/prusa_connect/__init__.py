"""
Farmhand's Prusa Connect plugin: Farmhand's Prusa printers' status and prints, from the farm's own Prusa Connect server
(Prusa's self-hosted printer server, https://github.com/prusa3d/prusa-connect) instead of each printer's PrusaLink.

    config.py     what the container is told (environment), and what it keeps itself (/data/settings.json): Prusa
                  Connect's address, the token it was given by pairing, which Prusa Connect printer is which
    farmhand.py   Farmhand's plugin API: the printers, and reporting each one's status (printers:report)
    connect.py    Prusa Connect's REST API: pairing with a short code, its printers and their state
    reporter.py   every few seconds, each linked printer's state from Prusa Connect, passed on to Farmhand
    server.py     the plugin's web server: /manifest, /health, its page and the page's API

Only Python's standard library. Prusa Connect is only called over its REST API: none of its code is used here.
"""
