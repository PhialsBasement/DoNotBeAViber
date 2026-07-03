# Changelog

## 0.2.0

- Sidebar settings panel: model list pulled live from your Claude Code install,
  effort options adapt to what the selected model supports
- Enter accepts, Esc discards (Tab still works); native accept toolbar always
  visible on suggestions
- Rejections log as `discard` events in the learning log
- Marketplace listing linked to the GitHub repo

## 0.1.0

Initial release.

- One sentence → one logical unit of code, via your own Claude Code install
- Model-side granularity gate with decomposition hints on rejection
- Ghost-text review flow: Enter/Tab accepts, Esc discards
- Read-only file context: generated code matches your naming and style
- Sidebar settings panel
- Local learning log (`.nlv/log.jsonl`)
