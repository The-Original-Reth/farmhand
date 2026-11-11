"""
Hello: the example Farmhand plugin, and the template to copy for your own.

It shows each of the farm's printers and how far along its print is, read live from Farmhand's plugin API, and
updates when a print starts or finishes. The parts, in the order a request meets them:

    config.py    the environment variables it's given, and its one setting (kept in its volume, /data)
    farmhand.py  talking to Farmhand's plugin API: the token, and every refusal turned into plain words
    watcher.py   keeping an up-to-date picture of the farm: Farmhand's events, a refresh now and then, retrying
    server.py    its own web server: /manifest, /health, the page and what the page asks for
    page.html    the page itself, shown inside Farmhand at /plugins/hello/

Only Python's standard library is used, so there's nothing to install.
"""
