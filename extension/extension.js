// @ts-check
// Don't Be a Viber — thin VS Code shell over the Python daemon (backend/server.py).
// Plain JavaScript on purpose: no compile step, no npm, no node_modules.
"use strict";

const vscode = require("vscode");
const cp = require("child_process");
const fs = require("fs");
const path = require("path");
const readline = require("readline");

// ---------------------------------------------------------------------------
// daemon client
// ---------------------------------------------------------------------------

class Daemon {
  /**
   * @param {string} workspace
   * @param {vscode.ExtensionContext} context
   */
  constructor(workspace, context) {
    const cfg = vscode.workspace.getConfiguration("nlv");
    const bundled = path.join(context.extensionPath, "backend", "server.py");
    const serverPy =
      cfg.get("backendPath") ||
      (fs.existsSync(bundled)
        ? bundled // packaged install: backend ships inside the extension
        : path.join(context.extensionPath, "..", "backend", "server.py")); // repo dev
    const args = [
      serverPy,
      "--workspace", workspace,
      "--model", String(cfg.get("model")),
      "--effort", String(cfg.get("effort")),
      "--max-lines", String(cfg.get("maxLines")),
      "--idle-minutes", String(cfg.get("session.idleMinutes")),
    ];
    this.dead = false;
    this.stderrTail = [];
    this.nextId = 1;
    /** @type {Map<number, {resolve: Function, reject: Function, timer: NodeJS.Timeout}>} */
    this.inflight = new Map();

    this.proc = cp.spawn(String(cfg.get("pythonPath")), args, {
      cwd: workspace,
      stdio: ["pipe", "pipe", "pipe"],
    });
    this.proc.on("error", (err) => this._die(`failed to start backend: ${err.message}`));
    this.proc.on("exit", (code) => this._die(`backend exited (code ${code})`));
    this.proc.stderr.on("data", (d) => {
      this.stderrTail.push(String(d));
      if (this.stderrTail.length > 20) this.stderrTail.shift();
    });
    readline.createInterface({ input: this.proc.stdout }).on("line", (line) => {
      let msg;
      try {
        msg = JSON.parse(line);
      } catch {
        return;
      }
      const waiter = this.inflight.get(msg.id);
      if (!waiter) return;
      this.inflight.delete(msg.id);
      clearTimeout(waiter.timer);
      if (msg.ok) waiter.resolve(msg.result);
      else waiter.reject(Object.assign(new Error(msg.error.message), { code: msg.error.code }));
    });
  }

  /** @param {string} reason */
  _die(reason) {
    if (this.dead) return;
    this.dead = true;
    const detail = this.stderrTail.join("").slice(-500);
    for (const [, waiter] of this.inflight) {
      clearTimeout(waiter.timer);
      waiter.reject(Object.assign(new Error(`${reason}${detail ? "\n" + detail : ""}`), { code: "backend-dead" }));
    }
    this.inflight.clear();
  }

  /**
   * @param {string} method
   * @param {object} [params]
   * @param {number} [timeoutMs]
   * @returns {Promise<any>}
   */
  request(method, params, timeoutMs = 90000) {
    if (this.dead) return Promise.reject(Object.assign(new Error("backend is not running"), { code: "backend-dead" }));
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.inflight.delete(id);
        reject(Object.assign(new Error(`no response from backend after ${timeoutMs / 1000}s`), { code: "timeout" }));
      }, timeoutMs);
      this.inflight.set(id, { resolve, reject, timer });
      this.proc.stdin.write(JSON.stringify({ id, method, params }) + "\n");
    });
  }

  dispose() {
    if (this.dead) return;
    try {
      this.proc.stdin.write(JSON.stringify({ id: 0, method: "shutdown" }) + "\n");
    } catch {}
    const proc = this.proc;
    setTimeout(() => {
      if (proc.exitCode === null) proc.kill();
    }, 2000);
  }
}

// ---------------------------------------------------------------------------
// extension state
// ---------------------------------------------------------------------------

/** @type {Daemon | null} */
let daemon = null;
/** @type {{uriString: string, line: number, codeBlock: string, indent: string, sentence: string, handling: string, generated: string, languageId: string, file: string | null} | null} */
let pendingSuggestion = null;
/** @type {vscode.StatusBarItem} */
let statusBar;

const COMMENT_PREFIX = {
  python: "#", ruby: "#", shellscript: "#", yaml: "#", r: "#", perl: "#",
  powershell: "#", coffeescript: "#", julia: "#", toml: "#", dockerfile: "#",
  makefile: "#", elixir: "#",
  lua: "--", sql: "--", haskell: "--",
  clojure: ";;", lisp: ";;",
  erlang: "%", latex: "%",
  asm: ";", nasm: ";", masm: ";", "asm-intel-x86-generic": ";", ini: ";",
  "arm": "@",
};

/** @param {string} languageId */
function commentPrefix(languageId) {
  return COMMENT_PREFIX[languageId] || "//";
}

/** Set/clear the pending suggestion and the keybinding context in lockstep.
 * The in-editor accept/discard hint is VS Code's native inline-suggestion
 * toolbar (editor.inlineSuggest.showToolbar = "always" — set on activation).
 * @param {typeof pendingSuggestion} p */
function setPending(p) {
  pendingSuggestion = p;
  vscode.commands.executeCommand("setContext", "nlv.suggestionVisible", !!p);
  if (statusBar) {
    if (p) {
      statusBar.text = "$(check) Enter accept  ·  $(x) Esc discard";
      statusBar.show();
    } else {
      setStatus("NLV", false);
    }
  }
}

/** @param {vscode.ExtensionContext} context */
function getDaemon(context) {
  if (daemon === null || daemon.dead) {
    const folders = vscode.workspace.workspaceFolders;
    const editor = vscode.window.activeTextEditor;
    const workspace =
      (folders && folders.length > 0 && folders[0].uri.fsPath) ||
      (editor && editor.document.uri.scheme === "file"
        ? path.dirname(editor.document.uri.fsPath)
        : null);
    if (!workspace) throw Object.assign(new Error("open a folder or a saved file first"), { code: "no-workspace" });
    daemon = new Daemon(workspace, context);
  }
  return daemon;
}

/** @param {string} text @param {boolean} busy */
function setStatus(text, busy) {
  statusBar.text = busy ? `$(sync~spin) ${text}` : `$(zap) ${text}`;
  statusBar.show();
}

// ---------------------------------------------------------------------------
// translate flow
// ---------------------------------------------------------------------------

/** @param {vscode.ExtensionContext} context */
async function translateLine(context) {
  const editor = vscode.window.activeTextEditor;
  if (!editor) return;
  const doc = editor.document;
  const lineNo = editor.selection.active.line;
  const lineText = doc.lineAt(lineNo).text;
  const indentMatch = lineText.match(/^\s*/);
  const indent = indentMatch ? indentMatch[0] : "";

  // sentence = the line minus a leading comment marker; OR, when the line is
  // existing code with a trailing comment, the trailing comment is the sentence
  // (a modify-this-line request — the model returns the replacement)
  let sentence = lineText.trim().replace(/^(#+|\/\/+|--|;+|%+)\s*/, "").trim();
  let originalCode = null; // modify-mode: the code the sentence is attached to
  const trailing = lineText.match(/^\s*(\S.*?)\s+(?:#+|\/\/+|--|;+)\s+(\S.*)$/);
  if (trailing && !/^(#|\/\/|--|;|%)/.test(trailing[1])) {
    sentence = trailing[2].trim();
    originalCode = trailing[1].trim();
  }
  if (!sentence) {
    vscode.window.setStatusBarMessage("NLV: nothing on this line to translate", 3000);
    return; // empty line: the only local no-op check
  }

  // the backend's Claude reads the file from DISK — flush unsaved edits first
  const isFile = doc.uri.scheme === "file";
  if (isFile && doc.isDirty) await doc.save();

  let d;
  try {
    d = getDaemon(context);
  } catch (e) {
    vscode.window.showErrorMessage(`NLV: ${e.message}`);
    return;
  }

  setPending(null);
  setStatus("NLV translating…", true);
  let result;
  try {
    result = await d.request("translate", {
      sentence,
      languageId: doc.languageId,
      file: isFile ? doc.uri.fsPath : null,
      line: lineNo + 1,
      indent,
    });
  } catch (e) {
    setStatus("NLV", false);
    showError(e);
    return;
  }
  setStatus("NLV", false);

  if (result.status === "rejected") {
    const prefix = commentPrefix(doc.languageId);
    const splitLines = result.split.map((s) => `${indent}${prefix} ${s}`).join("\n") + "\n";
    await editor.edit((b) => b.insert(new vscode.Position(lineNo + 1, 0), splitLines));
    vscode.window.showWarningMessage(
      `Don't be a viber! One logical unit per sentence — I left the split below as comments.`
    );
    return;
  }

  // status === "ok": preview the code as ghost text BELOW the sentence line.
  // (Inline suggestions must textually extend the current line — they cannot
  // rewrite it — so the sentence->comment conversion happens at accept time.)
  const codeBlock = result.code
    .replace(/\r\n/g, "\n")
    .replace(/\n+$/, "")
    .split("\n")
    .map((l) => (l.length ? indent + l : l))
    .join("\n");

  setPending({
    uriString: doc.uri.toString(),
    line: lineNo,
    codeBlock,
    indent,
    sentence,
    originalCode,
    handling: String(vscode.workspace.getConfiguration("nlv").get("sentenceHandling")),
    generated: result.code,
    languageId: doc.languageId,
    file: isFile ? vscode.workspace.asRelativePath(doc.uri) : null,
  });
  // ghost text renders at the cursor — park it at end of the sentence line
  const eol = doc.lineAt(lineNo).range.end;
  editor.selection = new vscode.Selection(eol, eol);
  // pull-based API, push-based need: trigger the provider now that we have data
  await vscode.commands.executeCommand("editor.action.inlineSuggest.trigger");
}

/** @param {Error & {code?: string}} e */
function showError(e) {
  const code = e.code || "internal";
  if (code === "claude-not-found") {
    vscode.window
      .showErrorMessage("NLV: the 'claude' CLI was not found. Install Claude Code and log in.", "Open install docs")
      .then((pick) => {
        if (pick) vscode.env.openExternal(vscode.Uri.parse("https://claude.com/claude-code"));
      });
  } else if (code === "over-scope") {
    vscode.window.showWarningMessage(`NLV: ${e.message}`);
  } else if (code === "busy") {
    vscode.window.setStatusBarMessage("NLV: still working on the previous sentence…", 3000);
  } else if (code === "cancelled") {
    // user asked for it; stay quiet
  } else {
    vscode.window.showErrorMessage(`NLV [${code}]: ${e.message}`);
  }
}

// ---------------------------------------------------------------------------
// sidebar settings view
// ---------------------------------------------------------------------------

const SETTING_KEYS = [
  "model", "effort", "sentenceHandling", "maxLines",
  "session.idleMinutes", "pythonPath", "backendPath",
];

class SettingsViewProvider {
  /** @param {vscode.ExtensionContext} context */
  constructor(context) {
    this.context = context;
    /** @type {vscode.WebviewView | null} */
    this.view = null;
  }

  /** @param {vscode.WebviewView} view */
  resolveWebviewView(view) {
    this.view = view;
    view.webview.options = { enableScripts: true };
    view.webview.html = settingsHtml();
    view.webview.onDidReceiveMessage(async (msg) => {
      if (msg.cmd === "ready") {
        this.sendConfig();
        this.sendModels(this.context.globalState.get("nlv.models"));
        this.refreshModels(); // async — updates the panel when the CLI answers
      } else if (msg.cmd === "set") {
        await vscode.workspace
          .getConfiguration("nlv")
          .update(msg.key, msg.value, vscode.ConfigurationTarget.Global);
      } else if (msg.cmd === "restart") {
        await vscode.commands.executeCommand("nlv.restartSession");
      } else if (msg.cmd === "log") {
        await vscode.commands.executeCommand("nlv.showLog");
      }
    });
  }

  /** @param {any} models */
  sendModels(models) {
    if (this.view && Array.isArray(models) && models.length) {
      this.view.webview.postMessage({ cmd: "models", models });
    }
  }

  /** Ask the actual Claude Code install what it offers (list_models control request). */
  async refreshModels() {
    try {
      const d = getDaemon(this.context);
      const res = await d.request("models", {}, 30000);
      if (res && Array.isArray(res.models) && res.models.length) {
        await this.context.globalState.update("nlv.models", res.models);
        this.sendModels(res.models);
        this.sendConfig();
      }
    } catch {
      /* claude missing / no workspace — static fallback options remain */
    }
  }

  sendConfig() {
    if (!this.view) return;
    const c = vscode.workspace.getConfiguration("nlv");
    const values = {};
    for (const k of SETTING_KEYS) values[k] = c.get(k);
    this.view.webview.postMessage({
      cmd: "config",
      values,
      backend: daemon && !daemon.dead ? "running" : "stopped (starts on first use)",
    });
  }
}

function settingsHtml() {
  return /* html */ `<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy"
      content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:;">
<style>
  body { font-family: var(--vscode-font-family); color: var(--vscode-foreground);
         font-size: var(--vscode-font-size); padding: 4px 12px 16px; }
  label { display: block; margin: 12px 0 3px; font-size: 11px; font-weight: 600;
          text-transform: uppercase; letter-spacing: .04em; opacity: .75; }
  input { width: 100%; box-sizing: border-box; padding: 4px 6px; border-radius: 2px;
          background: var(--vscode-input-background); color: var(--vscode-input-foreground);
          border: 1px solid var(--vscode-input-border, transparent); }
  select { width: 100%; box-sizing: border-box; padding: 4px 26px 4px 6px; border-radius: 2px;
          appearance: none; -webkit-appearance: none;
          background-color: var(--vscode-dropdown-background, var(--vscode-input-background));
          color: var(--vscode-dropdown-foreground, var(--vscode-input-foreground));
          border: 1px solid var(--vscode-dropdown-border, var(--vscode-input-border, transparent));
          background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'%3E%3Cpath d='M1 1l4 4 4-4' fill='none' stroke='%23888888' stroke-width='1.5' stroke-linecap='round'/%3E%3C/svg%3E");
          background-repeat: no-repeat; background-position: right 8px center; }
  select option { background: var(--vscode-dropdown-background); color: var(--vscode-dropdown-foreground); }
  input:focus, select:focus { outline: 1px solid var(--vscode-focusBorder); outline-offset: -1px; }
  .hint { font-size: 11px; opacity: .65; margin-top: 2px; }
  .row { margin-top: 16px; display: flex; gap: 6px; flex-wrap: wrap; }
  button { border: none; padding: 6px 10px; border-radius: 2px; cursor: pointer;
          background: var(--vscode-button-background); color: var(--vscode-button-foreground); }
  button.secondary { background: var(--vscode-button-secondaryBackground);
          color: var(--vscode-button-secondaryForeground); }
  #status { margin-top: 14px; font-size: 11px; opacity: .75; }
</style></head><body>

<label>Model</label>
<select data-key="model">
  <option value="sonnet">sonnet</option>
  <option value="opus">opus</option>
  <option value="haiku">haiku</option>
</select>
<div class="hint" id="modelHint">list loads from your Claude Code install…</div>

<label>Effort</label>
<select data-key="effort">
  <option value="low">low (fastest)</option>
  <option value="medium">medium</option>
  <option value="high">high</option>
</select>

<label>Sentence handling on accept</label>
<select data-key="sentenceHandling">
  <option value="comment">keep sentence as comment</option>
  <option value="strip">strip the sentence</option>
</select>

<label>Max generated lines</label>
<input data-key="maxLines" type="number" min="1" max="50">
<div class="hint">longer answers are refused as over-scope</div>

<label>Session idle timeout (minutes)</label>
<input data-key="session.idleMinutes" type="number" min="1" max="240">

<label>Python path</label>
<input data-key="pythonPath" placeholder="python">

<label>Backend path (advanced)</label>
<input data-key="backendPath" placeholder="auto">
<div class="hint">leave empty unless running the backend from a custom location</div>

<div class="row">
  <button id="restart">Restart session</button>
  <button id="log" class="secondary">Show learning log</button>
</div>
<div id="status"></div>

<script>
  const vscode = acquireVsCodeApi();
  let modelInfo = {}; // value -> model metadata from the Claude Code install

  function ensureOption(sel, value, label) {
    if (![...sel.options].some((o) => o.value === value)) sel.add(new Option(label, value));
  }

  function rebuildEffort() {
    const modelSel = document.querySelector('[data-key="model"]');
    const effortSel = document.querySelector('[data-key="effort"]');
    const cur = effortSel.value;
    const levels =
      (modelInfo[modelSel.value] && modelInfo[modelSel.value].supportedEffortLevels) ||
      ["low", "medium", "high"];
    effortSel.innerHTML = "";
    for (const l of levels) effortSel.add(new Option(l === "low" ? "low (fastest)" : l, l));
    ensureOption(effortSel, cur, cur + " (custom)");
    effortSel.value = cur;
  }

  window.addEventListener("message", (e) => {
    if (e.data.cmd === "models") {
      const sel = document.querySelector('[data-key="model"]');
      const cur = sel.value;
      modelInfo = {};
      sel.innerHTML = "";
      for (const m of e.data.models) {
        modelInfo[m.value] = m;
        const label =
          m.displayName && m.displayName.toLowerCase() !== m.value
            ? m.displayName + "  —  " + m.value
            : m.value;
        const o = new Option(label, m.value);
        o.title = m.description || "";
        sel.add(o);
      }
      ensureOption(sel, cur, cur + " (custom)");
      sel.value = cur;
      const hint = modelInfo[cur] && modelInfo[cur].description;
      document.getElementById("modelHint").textContent = hint || "models from your Claude Code install";
      rebuildEffort();
      return;
    }
    if (e.data.cmd !== "config") return;
    for (const el of document.querySelectorAll("[data-key]")) {
      const v = e.data.values[el.dataset.key];
      if (v === undefined || v === null) continue;
      const s = String(v);
      if (el.tagName === "SELECT") ensureOption(el, s, s + " (custom)");
      el.value = s;
    }
    rebuildEffort();
    document.getElementById("status").textContent = "backend: " + e.data.backend;
  });
  document.querySelector('[data-key="model"]').addEventListener("change", () => {
    const m = modelInfo[document.querySelector('[data-key="model"]').value];
    document.getElementById("modelHint").textContent = (m && m.description) || "";
    rebuildEffort();
  });
  for (const el of document.querySelectorAll("[data-key]")) {
    el.addEventListener("change", () => {
      const value = el.type === "number" ? Number(el.value) : el.value;
      vscode.postMessage({ cmd: "set", key: el.dataset.key, value });
    });
  }
  document.getElementById("restart").addEventListener("click", () => vscode.postMessage({ cmd: "restart" }));
  document.getElementById("log").addEventListener("click", () => vscode.postMessage({ cmd: "log" }));
  vscode.postMessage({ cmd: "ready" });
</script>
</body></html>`;
}

// ---------------------------------------------------------------------------
// activation
// ---------------------------------------------------------------------------

/** @param {vscode.ExtensionContext} context */
function activate(context) {
  statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 90);
  setStatus("NLV", false);

  // the accept/discard hint attached to ghost text is VS Code's own
  // inline-suggestion toolbar; default is hover-only — make it always visible
  const inlineCfg = vscode.workspace.getConfiguration("editor.inlineSuggest");
  if (inlineCfg.get("showToolbar") !== "always") {
    inlineCfg.update("showToolbar", "always", vscode.ConfigurationTarget.Global);
  }

  const settingsProvider = new SettingsViewProvider(context);
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider("nlv.settingsView", settingsProvider)
  );

  context.subscriptions.push(
    statusBar,

    vscode.commands.registerCommand("nlv.translateLine", () => translateLine(context)),

    vscode.commands.registerCommand("nlv.restartSession", async () => {
      if (daemon && !daemon.dead) {
        try {
          await daemon.request("restart", {}, 10000);
          vscode.window.setStatusBarMessage("NLV: session restarted", 3000);
          return;
        } catch {}
      }
      if (daemon) daemon.dispose();
      daemon = null;
      vscode.window.setStatusBarMessage("NLV: backend will respawn on next use", 3000);
    }),

    vscode.commands.registerCommand("nlv.showLog", async () => {
      const folders = vscode.workspace.workspaceFolders;
      if (!folders || folders.length === 0) return;
      const logUri = vscode.Uri.file(path.join(folders[0].uri.fsPath, ".nlv", "log.jsonl"));
      try {
        await vscode.window.showTextDocument(logUri);
      } catch {
        vscode.window.showInformationMessage("NLV: no learning log yet — translate something first.");
      }
    }),

    // Enter -> commit the visible inline suggestion (old-school accept)
    vscode.commands.registerCommand("nlv.accept", () =>
      vscode.commands.executeCommand("editor.action.inlineSuggest.commit")
    ),

    // Esc -> hide + log the discard
    vscode.commands.registerCommand("nlv.dismiss", () => {
      const p = pendingSuggestion;
      setPending(null);
      vscode.commands.executeCommand("editor.action.inlineSuggest.hide");
      if (p && daemon && !daemon.dead) {
        daemon
          .request("logEvent", {
            event: "discard",
            sentence: p.sentence,
            generated: p.generated,
            languageId: p.languageId,
            file: p.file,
          })
          .catch(() => {});
      }
    }),

    // fires via InlineCompletionItem.command when the suggestion is committed
    vscode.commands.registerCommand("nlv._accepted", async (payload) => {
      setPending(null);
      if (!payload) return;
      // the code was just inserted below; now convert (or strip) the sentence line
      const uri = vscode.Uri.parse(payload.uriString);
      const edit = new vscode.WorkspaceEdit();
      if (payload.handling === "strip") {
        edit.delete(uri, new vscode.Range(payload.line, 0, payload.line + 1, 0));
      } else {
        const doc = vscode.workspace.textDocuments.find((d) => d.uri.toString() === payload.uriString);
        const lineRange = doc ? doc.lineAt(payload.line).range : null;
        if (lineRange) {
          // modify-mode keeps the replaced code visible in the trail — never
          // silently delete what the sentence was attached to
          const was = payload.originalCode ? ` (was: ${payload.originalCode})` : "";
          edit.replace(uri, lineRange,
            `${payload.indent}${commentPrefix(payload.languageId)} ${payload.sentence}${was}`);
        }
      }
      await vscode.workspace.applyEdit(edit);
      if (daemon && !daemon.dead) {
        daemon
          .request("logEvent", {
            event: "accept",
            sentence: payload.sentence,
            generated: payload.generated,
            languageId: payload.languageId,
            file: payload.file,
          })
          .catch(() => {});
      }
    }),

    vscode.languages.registerInlineCompletionItemProvider(
      { pattern: "**" },
      {
        provideInlineCompletionItems(doc, position) {
          const p = pendingSuggestion;
          if (!p || doc.uri.toString() !== p.uriString || position.line !== p.line) return [];
          // pure insertion at the cursor: "\n" + code — never rewrites the line,
          // so the inline-suggestion prefix rule is satisfied
          const item = new vscode.InlineCompletionItem(
            "\n" + p.codeBlock,
            new vscode.Range(position, position)
          );
          item.command = { command: "nlv._accepted", title: "nlv accepted", arguments: [p] };
          return [item];
        },
      }
    ),

    // moving off the sentence line abandons the pending suggestion
    vscode.window.onDidChangeTextEditorSelection((e) => {
      const p = pendingSuggestion;
      if (p && e.textEditor.document.uri.toString() === p.uriString &&
          e.selections[0] && e.selections[0].active.line !== p.line) {
        setPending(null);
      }
    }),

    // config change -> recycle the daemon so new model/effort/etc. apply
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration("nlv")) {
        if (daemon) {
          daemon.dispose();
          daemon = null;
        }
        settingsProvider.sendConfig();
      }
    })
  );
}

function deactivate() {
  if (daemon) daemon.dispose();
  daemon = null;
}

module.exports = { activate, deactivate };
