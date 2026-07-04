# Changelog

## 0.4.0

- Mandatory Read: an ok answer for a file-backed request is never accepted
  unless the model actually read your file — unread answers are discarded with
  an explicit refusal and re-asked for the life of the request
- Referent rule closes the naming loophole: a sentence saying "discount" when
  your file has "discountRate" gets rejected with the real name pointed out
- Modify-this-line requests: write your sentence as a trailing comment after
  existing code ("code  # wrap this in an if") — wrapping/guarding the
  statement is one unit, and the replaced code is preserved in the comment
  trail ("(was: ...)")
- One-entry splits outlawed: if the rejection could be phrased as a single
  doable sentence, it's accepted instead

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
