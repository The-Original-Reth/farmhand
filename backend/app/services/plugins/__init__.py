"""
Plugins: other people's programs, each in its own container, that read Farmhand through the plugin API
(/plugin-api/v1/, docs/plugins.md).
  manifest.py   checking a plugin's farmhand-plugin.json, and the permissions there are
  registry.py   the plugins installed, their tokens, and knowing a plugin by its token
  answers.py    what the plugin API answers (printers, cameras, a print, the farm)
  events.py     what plugins hear on /events (prints starting and ending, printers coming and going)
  cache.py      answers kept a few seconds, so plugins can't load Farmhand
"""
