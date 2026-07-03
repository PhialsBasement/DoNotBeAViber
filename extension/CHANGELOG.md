# Changelog

## 0.3.0

- Gate hardened: referents must be real — the model can no longer invent
  variable names, symbols, data sizes, or platform choices your sentence and
  file don't contain; rejections now ask for the missing piece by name
- Gate balanced the other way: implied destinations ("convert x to uppercase"
  reassigns x) and same-value transformation chains count as one unit —
  verified by a new 20-sentence false-rejection sweep alongside the
  adversarial suite
- Correct comment syntax for assembly languages on accept

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
