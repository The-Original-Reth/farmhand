"""
Plugins: other people's programs, each in its own container (on this machine or another on the farm's network), that
read Farmhand through the plugin API (/plugin-api/v1/, docs/plugins.md).
  manifest.py   checking a plugin's farmhand-plugin.json, and the permissions there are
  registry.py   the plugins added, their tokens, switching one off, knowing a plugin by its token, the settings copy
  remote.py     talking to a plugin where it runs: its address checked, its /manifest and health asked
  health.py     the worker asking every plugin whether it's well, every 30 s
  limits.py     how often a token may call the plugin API
  pages.py      a plugin's page passed on from where it runs (/plugins/<id>/page/...), and farmhand-plugin.js
  answers.py    what the plugin API answers (printers, cameras, a print, the farm)
  events.py     what plugins hear on /events (prints starting and ending, printers coming and going)
  cache.py      answers kept a few seconds, so plugins can't load Farmhand
"""
