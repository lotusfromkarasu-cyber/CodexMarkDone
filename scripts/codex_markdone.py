"""Local Codex transcript reader with Word MathML clipboard support.

This file intentionally uses only the Python standard library so it can run on
Windows without a separate runtime dependency. It accepts Codex JSONL logs and
plain Markdown/text files. The GUI is a small local companion panel: the
selection is made in this panel, not by patching the Codex desktop DOM.
"""

from __future__ import annotations

import argparse
import ctypes
import html
import http.server
import json
import os
import re
import subprocess
import sys
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from urllib.parse import urlparse


GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ϵ",
    "varepsilon": "ε", "zeta": "ζ", "eta": "η", "theta": "θ", "vartheta": "ϑ",
    "iota": "ι", "kappa": "κ", "lambda": "λ", "mu": "μ", "nu": "ν",
    "xi": "ξ", "pi": "π", "varpi": "ϖ", "rho": "ρ", "varrho": "ϱ",
    "sigma": "σ", "varsigma": "ς", "tau": "τ", "upsilon": "υ", "phi": "ϕ",
    "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω", "Gamma": "Γ",
    "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ", "Pi": "Π",
    "Sigma": "Σ", "Upsilon": "Υ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
}

OPERATORS = {
    "cdot": "⋅", "times": "×", "pm": "±", "mp": "∓", "le": "≤", "leq": "≤",
    "ge": "≥", "geq": "≥", "neq": "≠", "ne": "≠", "approx": "≈", "sim": "∼",
    "to": "→", "rightarrow": "→", "leftarrow": "←", "leftrightarrow": "↔",
    "Rightarrow": "⇒", "Leftrightarrow": "⇔", "infty": "∞", "partial": "∂",
    "nabla": "∇", "forall": "∀", "exists": "∃", "in": "∈", "notin": "∉",
    "sum": "∑", "prod": "∏", "int": "∫", "oint": "∮", "cap": "∩", "cup": "∪",
    "land": "∧", "lor": "∨", "ldots": "…", "cdots": "⋯", "quad": " ",
}

ACCENTS = {"hat": "^", "bar": "¯", "overline": "¯", "vec": "→", "tilde": "~"}


def xml_escape(value: str) -> str:
    return html.escape(value, quote=False)


def _read_group(source: str, index: int) -> tuple[str, int]:
    if index >= len(source) or source[index] != "{":
        return (source[index:index + 1], min(index + 1, len(source)))
    depth = 1
    pos = index + 1
    start = pos
    while pos < len(source) and depth:
        if source[pos] == "\\":
            pos += 2
            continue
        if source[pos] == "{":
            depth += 1
        elif source[pos] == "}":
            depth -= 1
        pos += 1
    return source[start:pos - 1] if depth == 0 else source[start:], pos


def _read_argument(source: str, index: int) -> tuple[str, int]:
    while index < len(source) and source[index].isspace():
        index += 1
    if index < len(source) and source[index] == "{":
        return _read_group(source, index)
    if index < len(source) and source[index] == "\\":
        end = index + 1
        while end < len(source) and source[end].isalpha():
            end += 1
        return source[index:end], end
    return source[index:index + 1], min(index + 1, len(source))


def _token(text: str, kind: str | None = None) -> str:
    escaped = xml_escape(text)
    if kind == "number":
        return f"<mn>{escaped}</mn>"
    if kind == "operator":
        return f"<mo>{escaped}</mo>"
    if kind == "text":
        return f"<mtext>{escaped}</mtext>"
    return f"<mi>{escaped}</mi>"


def _parse_sequence(source: str) -> str:
    parts: list[str] = []
    index = 0
    while index < len(source):
        if source[index].isspace():
            index += 1
            continue
        if source[index] == "}":
            index += 1
            continue

        atom, index = _parse_atom(source, index)
        sup = sub = None
        while index < len(source) and source[index] in "^_":
            marker = source[index]
            argument, index = _read_argument(source, index + 1)
            rendered = _parse_sequence(argument)
            rendered = rendered if rendered.startswith("<mrow>") else f"<mrow>{rendered}</mrow>"
            if marker == "^":
                sup = rendered
            else:
                sub = rendered
        if sub is not None and sup is not None:
            atom = f"<msubsup>{atom}{sub}{sup}</msubsup>"
        elif sub is not None:
            atom = f"<msub>{atom}{sub}</msub>"
        elif sup is not None:
            atom = f"<msup>{atom}{sup}</msup>"
        parts.append(atom)
    return "".join(parts)


def _parse_matrix(body: str, display: bool) -> str:
    rows = re.split(r"\\\\", body)
    rendered_rows = []
    for row in rows:
        cells = row.split("&")
        rendered_rows.append("<mtr>" + "".join(f"<mtd><mrow>{_parse_sequence(cell)}</mrow></mtd>" for cell in cells) + "</mtr>")
    return "<mtable>" + "".join(rendered_rows) + "</mtable>"


def _parse_atom(source: str, index: int) -> tuple[str, int]:
    char = source[index]
    if char == "{":
        content, end = _read_group(source, index)
        return f"<mrow>{_parse_sequence(content)}</mrow>", end
    if char == "\\":
        end = index + 1
        while end < len(source) and source[end].isalpha():
            end += 1
        command = source[index + 1:end]
        if not command and end < len(source):
            return _token(source[end], "operator"), end + 1
        if command in ("left", "right"):
            while end < len(source) and source[end].isspace():
                end += 1
            if end < len(source):
                return f'<mo fence="true">{xml_escape(source[end])}</mo>', end + 1
        if command in ("frac", "dfrac", "tfrac"):
            num, end = _read_argument(source, end)
            den, end = _read_argument(source, end)
            return f"<mfrac><mrow>{_parse_sequence(num)}</mrow><mrow>{_parse_sequence(den)}</mrow></mfrac>", end
        if command == "sqrt":
            while end < len(source) and source[end].isspace():
                end += 1
            degree = None
            if end < len(source) and source[end] == "[":
                close = source.find("]", end + 1)
                if close >= 0:
                    degree = source[end + 1:close]
                    end = close + 1
            body, end = _read_argument(source, end)
            inner = f"<mrow>{_parse_sequence(body)}</mrow>"
            return (f"<mroot>{inner}<mrow>{_parse_sequence(degree)}</mrow></mroot>" if degree is not None else f"<msqrt>{inner}</msqrt>"), end
        if command in ("text", "mathrm", "operatorname"):
            body, end = _read_argument(source, end)
            tag = "mtext" if command == "text" else "mi"
            return f"<{tag}>{xml_escape(re.sub(r'\\([A-Za-z]+)', lambda m: GREEK.get(m.group(1), m.group(1)), body))}</{tag}>", end
        if command in ("mathbf", "boldsymbol", "mathbb", "mathcal", "mathit", "mathrm"):
            body, end = _read_argument(source, end)
            variant = {"mathbf": "bold", "boldsymbol": "bold-italic", "mathbb": "double-struck", "mathcal": "script", "mathit": "italic", "mathrm": "normal"}[command]
            return f'<mstyle mathvariant="{variant}"><mrow>{_parse_sequence(body)}</mrow></mstyle>', end
        if command in ACCENTS:
            body, end = _read_argument(source, end)
            accent = xml_escape(ACCENTS[command])
            return f'<mover accent="true"><mrow>{_parse_sequence(body)}</mrow><mo>{accent}</mo></mover>', end
        if command in GREEK:
            return _token(GREEK[command]), end
        if command in OPERATORS:
            return _token(OPERATORS[command], "operator"), end
        if command in ("begin", "end"):
            env, end = _read_argument(source, end)
            if command == "begin":
                close_marker = "\\end{" + env + "}"
                close = source.find(close_marker, end)
                if close >= 0:
                    body = source[end:close]
                    return _parse_matrix(body, True) if env in ("matrix", "pmatrix", "bmatrix", "smallmatrix") else f"<mrow>{_parse_sequence(body)}</mrow>", close + len(close_marker)
            return "", end
        return _token(command or "\\"), end
    if char.isdigit():
        end = index + 1
        while end < len(source) and (source[end].isdigit() or source[end] == "."):
            end += 1
        return _token(source[index:end], "number"), end
    if char.isalpha():
        return _token(char), index + 1
    if char in "()[]|,;:+-=*/<>!":
        return _token(char, "operator"), index + 1
    return _token(char, "operator"), index + 1


def latex_to_mathml(latex: str, display: bool = True) -> str:
    body = latex.strip()
    return f'<math xmlns="http://www.w3.org/1998/Math/MathML"{(" display=\"block\"" if display else "")}><mrow>{_parse_sequence(body)}</mrow></math>'


FORMULA_PATTERNS = [
    re.compile(r"\\\[(.*?)\\\]", re.S),
    re.compile(r"\\\((.*?)\\\)", re.S),
    re.compile(r"\$\$(.*?)\$\$", re.S),
    re.compile(r"(?<!\$)\$(?!\$)(.*?)(?<!\$)\$(?!\$)", re.S),
]


def find_formulas(text: str) -> list[tuple[int, int, str, bool]]:
    # Some JSONL/export paths contain doubled delimiter slashes. Normalize only
    # the delimiter characters for scanning; LaTeX command backslashes remain.
    text = re.sub(r"\\\\(?=[()\[\]])", r"\\", text)
    matches: list[tuple[int, int, str, bool]] = []
    for pattern in FORMULA_PATTERNS:
        for match in pattern.finditer(text):
            display = text[match.start():match.start() + 2] in ("\\[", "$$")
            matches.append((match.start(), match.end(), match.group(1), display))
    matches.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    result: list[tuple[int, int, str, bool]] = []
    occupied = -1
    for item in matches:
        if item[0] >= occupied:
            result.append(item)
            occupied = item[1]
    return result


def extract_formula(text: str) -> tuple[str, bool] | None:
    found = find_formulas(text)
    if found:
        _, _, body, display = found[0]
        return body.strip(), display
    stripped = text.strip()
    if stripped.startswith("\\") or any(command in stripped for command in ("^", "_", "\\frac", "\\sqrt")):
        return stripped, False
    return None


def normalize_markdown(text: str) -> str:
    # Protect code spans/fences first. Formula delimiters inside code must stay
    # literal, and no global backslash replacement is safe for Windows paths.
    protected: list[str] = []
    def stash(match: re.Match[str]) -> str:
        protected.append(match.group(0))
        return f"\x00CODE{len(protected) - 1}\x00"
    text = re.sub(r"```[\s\S]*?```|`[^`\n]*`", stash, text)
    # Normalize only escaped delimiters. Do not globally collapse backslashes.
    text = re.sub(r"\\\\(?=[()\[\]])", r"\\", text)
    text = re.sub(r"\\\[(.*?)\\\]", lambda m: "$$" + m.group(1).strip() + "$$", text, flags=re.S)
    text = re.sub(r"\\\((.*?)\\\)", lambda m: "$" + m.group(1).strip() + "$", text, flags=re.S)
    for index, original in enumerate(protected):
        text = text.replace(f"\x00CODE{index}\x00", original)
    return text


def formula_html(text: str) -> str:
    # Use the same delimiter-normalized view for scanning and slicing. This is
    # important when an exported JSONL message contains doubled delimiters.
    text = normalize_markdown(text)
    chunks: list[str] = []
    cursor = 0
    for start, end, body, display in find_formulas(text):
        chunks.append(html.escape(text[cursor:start]).replace("\n", "<br>"))
        chunks.append(latex_to_mathml(body, display))
        cursor = end
    chunks.append(html.escape(text[cursor:]).replace("\n", "<br>"))
    return "".join(chunks)


def cf_html(fragment: str) -> bytes:
    prefix = "Version:0.9\r\nStartHTML:{start_html:010d}\r\nEndHTML:{end_html:010d}\r\nStartFragment:{start_fragment:010d}\r\nEndFragment:{end_fragment:010d}\r\n"
    marker_start, marker_end = "<!--StartFragment-->", "<!--EndFragment-->"
    document = "<html><body>" + marker_start + fragment + marker_end + "</body></html>"
    header = prefix.format(start_html=0, end_html=0, start_fragment=0, end_fragment=0)
    start_html = len(header.encode("utf-8"))
    end_html = start_html + len(document.encode("utf-8"))
    start_fragment = start_html + len(("<html><body>" + marker_start).encode("utf-8"))
    end_fragment = end_html - len((marker_end + "</body></html>").encode("utf-8"))
    header = prefix.format(start_html=start_html, end_html=end_html, start_fragment=start_fragment, end_fragment=end_fragment)
    return (header + document).encode("utf-8")


def _global_bytes(data: bytes):
    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    handle = kernel32.GlobalAlloc(0x0002, len(data))
    if not handle:
        raise OSError("GlobalAlloc failed")
    pointer = kernel32.GlobalLock(handle)
    if not pointer:
        kernel32.GlobalFree(handle)
        raise OSError("GlobalLock failed")
    ctypes.memmove(pointer, data, len(data))
    kernel32.GlobalUnlock(handle)
    return handle


def set_windows_clipboard(plain: str, mathml: str | None = None, rich_html: str | None = None) -> None:
    if sys.platform == "darwin":
        try:
            from AppKit import NSPasteboard, NSPasteboardTypeHTML, NSPasteboardTypeString
        except ImportError:
            subprocess.run(["pbcopy"], input=plain.encode("utf-8"), check=True)
            return
        if mathml and not rich_html:
            rich_html = f"<!doctype html><html><body>{mathml}</body></html>"
        pasteboard = NSPasteboard.generalPasteboard()
        pasteboard.clearContents()
        if not pasteboard.setString_forType_(plain, NSPasteboardTypeString):
            raise OSError("无法写入 macOS 剪贴板")
        if rich_html and not pasteboard.setString_forType_(rich_html, NSPasteboardTypeHTML):
            raise OSError("无法写入 HTML 剪贴板")
        return
    if sys.platform != "win32":
        raise RuntimeError("剪贴板目前支持 Windows 和 macOS")
    user32 = ctypes.windll.user32
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.restype = ctypes.c_bool
    user32.EmptyClipboard.restype = ctypes.c_bool
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    user32.RegisterClipboardFormatW.argtypes = [ctypes.c_wchar_p]
    user32.RegisterClipboardFormatW.restype = ctypes.c_uint
    if not user32.OpenClipboard(None):
        raise OSError("无法打开 Windows 剪贴板")
    try:
        user32.EmptyClipboard()
        unicode_id = 13  # CF_UNICODETEXT
        if not user32.SetClipboardData(unicode_id, _global_bytes((plain + "\0").encode("utf-16-le"))):
            raise OSError("无法写入文本剪贴板")
        if rich_html:
            html_id = user32.RegisterClipboardFormatW("HTML Format")
            if not user32.SetClipboardData(html_id, _global_bytes(rich_html)):
                raise OSError("无法写入 HTML 剪贴板")
        if mathml:
            payload = (mathml + "\0").encode("utf-16-le")
            for name in ("MathML", "MathML Presentation"):
                fmt_id = user32.RegisterClipboardFormatW(name)
                if not user32.SetClipboardData(fmt_id, _global_bytes(payload)):
                    raise OSError(f"无法写入 {name} 剪贴板")
    finally:
        user32.CloseClipboard()


def copy_markdown(text: str) -> None:
    normalized = normalize_markdown(text)
    set_windows_clipboard(normalized)


def copy_word(text: str, formula_only: bool = False) -> None:
    found = extract_formula(text)
    if formula_only:
        if not found:
            raise ValueError("当前选择中没有识别到 LaTeX 公式")
        body, display = found
        mathml = latex_to_mathml(body, display=True)
        set_windows_clipboard(body, mathml=mathml)
        return
    if found and text.strip() == text.strip()[0:len(text.strip())] and len(find_formulas(text)) == 1 and text.strip().startswith(("$", "\\")):
        body, display = found
        set_windows_clipboard(body, mathml=latex_to_mathml(body, display=True))
        return
    normalized = normalize_markdown(text)
    set_windows_clipboard(normalized, rich_html=cf_html(formula_html(text)))


def _first_text(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_first_text(item) for item in value)
    if isinstance(value, dict):
        for key in ("text", "message", "content", "summary", "output", "delta"):
            if key in value:
                result = _first_text(value[key])
                if result:
                    return result
    return ""


def clean_message_text(text: str) -> str:
    """Remove Codex-injected ambient metadata from the visible conversation."""
    text = re.sub(r"\n?<in-app-browser-context\b[^>]*>[\s\S]*?</in-app-browser-context>\s*", "\n", text, flags=re.I)
    text = re.sub(r"\n?<environment_context\b[^>]*>[\s\S]*?</environment_context>\s*", "\n", text, flags=re.I)
    text = re.sub(r"\n?</?image\b[^>]*>\s*", "\n", text, flags=re.I)
    # File and environment notes are useful to the agent but are not part of
    # the rendered chat reply. Keep the user's actual request after the marker.
    text = re.sub(r"(?ms)^# Files mentioned by the user:.*?(?=^## My request:)", "", text)
    text = re.sub(r"(?m)^## My request:\s*", "", text)
    return text.strip()


def parse_jsonl_messages(path: Path) -> list[dict[str, str]]:
    """Read only visible user/assistant messages from a Codex JSONL transcript."""
    messages: list[dict[str, str]] = []
    last_key: tuple[str, str] | None = None
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = obj.get("payload", obj) if isinstance(obj, dict) else {}
            if not isinstance(payload, dict):
                continue
            event_type = str(payload.get("type", obj.get("type", "")))
            role = str(payload.get("role", ""))
            if role not in {"user", "assistant"} and event_type not in {"user_message", "assistant_message", "agent_message"}:
                continue
            text = _first_text(payload)
            metadata = payload.get("internal_chat_message_metadata_passthrough", {})
            content_kinds = metadata.get("content_item_kinds", []) if isinstance(metadata, dict) else []
            if any(kind in {"agents_md.instructions", "environments.environment_context"} for kind in content_kinds):
                continue
            if text.lstrip().startswith("# AGENTS.md instructions") and "## My request:" not in text:
                continue
            text = clean_message_text(text)
            if not text:
                continue
            normalized_role = "user" if role == "user" or event_type == "user_message" else "assistant"
            key = (normalized_role, text)
            # Streaming/event logs may repeat the same item consecutively. Do
            # not suppress a later identical answer in a real conversation.
            if key == last_key:
                continue
            last_key = key
            messages.append({
                "role": normalized_role,
                "label": "用户" if normalized_role == "user" else "Codex",
                "text": text,
                "timestamp": str(obj.get("timestamp", "")),
            })
    return messages


def parse_jsonl(path: Path) -> str:
    blocks: list[str] = []
    for message in parse_jsonl_messages(path):
        blocks.append(f"### {message['label']}\n\n{message['text']}")
    return "\n\n".join(blocks)


def find_session_files() -> list[Path]:
    home = Path(os.environ.get("USERPROFILE", Path.home()))
    roots = [home / ".codex" / "sessions", home / ".codex" / "archived_sessions"]
    files: list[Path] = []
    for root in roots:
        if root.exists():
            files.extend(root.rglob("*.jsonl"))
    return sorted(set(files), key=lambda p: p.stat().st_mtime, reverse=True)


def find_current_session(session_id: str | None = None) -> Path | None:
    """Resolve the Codex task that launched this process.

    Codex Desktop/CLI exposes the active task id to processes it starts. The
    local JSONL filename contains that id, so this stays local and avoids
    guessing from the newest session when a task id is available.
    """
    active_id = session_id or os.environ.get("CODEX_THREAD_ID") or os.environ.get("CODEX_SESSION_ID")
    if not active_id:
        return None
    needle = active_id.lower()
    matches = [path for path in find_session_files() if needle in path.name.lower()]
    return matches[0] if matches else None


def _formula_markup(body: str, display: bool) -> str:
    escaped_body = html.escape(body.strip(), quote=True)
    classes = "formula formula-display" if display else "formula formula-inline"
    mathml = latex_to_mathml(body, display=display)
    return f'<span class="{classes}" data-latex="{escaped_body}" data-display="{"1" if display else "0"}" title="单击选中公式">{mathml}</span>'


def render_inline_html(source: str) -> str:
    """Render the Markdown subset used by Codex replies, including MathML."""
    # Protect code spans before delimiter normalization so literal \(...\) in
    # code never becomes a formula.
    protected: dict[str, str] = {}

    def stash_code(match: re.Match[str]) -> str:
        token = f"\x00CODE{len(protected)}\x00"
        protected[token] = f"<code>{html.escape(match.group(1))}</code>"
        return token

    work = re.sub(r"`([^`\n]+)`", stash_code, source)
    work = normalize_markdown(work)
    formula_tokens: dict[str, str] = {}
    chunks: list[str] = []
    cursor = 0
    for start, end, body, display in find_formulas(work):
        chunks.append(html.escape(work[cursor:start]))
        token = f"\x00FORMULA{len(formula_tokens)}\x00"
        formula_tokens[token] = _formula_markup(body, display)
        chunks.append(token)
        cursor = end
    chunks.append(html.escape(work[cursor:]))
    rendered = "".join(chunks)
    rendered = re.sub(
        r"\[([^\]]+)\]\((https?://[^\s)]+)\)",
        lambda m: f'<a href="{html.escape(m.group(2), quote=True)}" target="_blank" rel="noreferrer">{m.group(1)}</a>',
        rendered,
    )
    rendered = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: f"<strong>{m.group(1) or m.group(2)}</strong>", rendered)
    rendered = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)|(?<!_)_([^_\n]+)_(?!_)", lambda m: f"<em>{m.group(1) or m.group(2)}</em>", rendered)
    rendered = re.sub(r"~~(.+?)~~", r"<del>\1</del>", rendered)
    for token, value in protected.items():
        rendered = rendered.replace(token, value)
    for token, value in formula_tokens.items():
        rendered = rendered.replace(token, value)
    return rendered


def _line_element(raw: str, body_html: str, kind: str = "") -> str:
    data_raw = html.escape(raw, quote=True)
    kind_class = f" {kind}" if kind else ""
    return (
        f'<div class="md-line{kind_class}" data-raw="{data_raw}">'
        f'<div class="line-body">{body_html or "&nbsp;"}</div>'
        f'<button class="line-pick" type="button" title="选择这一行">选行</button></div>'
    )


def render_markdown_html(source: str) -> str:
    """Render a reply into selectable chat-like blocks."""
    output: list[str] = []
    # JSONL copied from some Codex export paths doubles only the delimiter
    # slash (``\\[``/``\\(``). Normalize that marker for the visual parser;
    # LaTeX command backslashes remain untouched.
    render_source = source.replace("\r\n", "\n").replace("\r", "\n")
    raw_lines = render_source.split("\n")
    # Normalize doubled delimiters only in prose. A code block may legitimately
    # contain the literal characters ``\\\\(`` or ``\\\\[`` and must remain
    # byte-for-byte visible to the user.
    normalized_lines: list[str] = []
    source_in_code = False
    for raw_line in raw_lines:
        fence = re.match(r"^\s*```\s*[\w+-]*\s*$", raw_line)
        normalized_lines.append(raw_line if source_in_code else re.sub(r"\\\\(?=[()\[\]])", r"\\", raw_line))
        if fence:
            source_in_code = not source_in_code
    raw_lines = normalized_lines
    table_tokens: dict[str, str] = {}
    lines: list[str] = []
    line_index = 0
    while line_index < len(raw_lines):
        candidate = raw_lines[line_index]
        if "|" in candidate and line_index + 1 < len(raw_lines) and re.match(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$", raw_lines[line_index + 1]):
            rows = [candidate]
            line_index += 1
            while line_index < len(raw_lines) and "|" in raw_lines[line_index] and raw_lines[line_index].strip():
                rows.append(raw_lines[line_index])
                line_index += 1
            if len(rows) >= 2:
                def cells(row: str) -> list[str]:
                    value = row.strip().strip("|")
                    return [part.strip() for part in value.split("|")]
                header = cells(rows[0])
                body_rows = [cells(row) for row in rows[2:]]
                raw_table = "\n".join(rows)
                table_html = ['<div class="table-wrap"><table><thead><tr>']
                table_html.extend(f"<th>{render_inline_html(cell)}</th>" for cell in header)
                table_html.append("</tr></thead>")
                if body_rows:
                    table_html.append("<tbody>")
                    for row in body_rows:
                        table_html.append("<tr>" + "".join(f"<td>{render_inline_html(cell)}</td>" for cell in row) + "</tr>")
                    table_html.append("</tbody>")
                table_html.append("</table>")
                table_html.append(f'<button class="block-pick table-pick" type="button" title="选择表格" data-raw="{html.escape(raw_table, quote=True)}">选择表格</button></div>')
                token = f"\x00TABLE{len(table_tokens)}\x00"
                table_tokens[token] = "".join(table_html)
                lines.append(token)
                continue
            line_index -= 1
        lines.append(candidate)
        line_index += 1
    in_code = False
    code_language = ""
    code_lines: list[str] = []
    display_lines: list[str] = []
    display_delimiter: str | None = None

    def flush_code() -> None:
        if not code_lines:
            return
        raw_code = "\n".join(code_lines)
        data_raw = html.escape(raw_code, quote=True)
        code_html = "\n".join(
            f'<span class="code-line" data-raw="{html.escape(line, quote=True)}">{html.escape(line) or " "}</span>'
            for line in code_lines
        )
        language = f'<span class="code-language">{html.escape(code_language)}</span>' if code_language else ""
        output.append(
            f'<div class="code-wrap" data-raw="{data_raw}">{language}<pre>{code_html}</pre>'
            f'<button class="block-pick" type="button" title="选择代码块">选择代码块</button></div>'
        )

    for line in lines:
        if line in table_tokens:
            output.append(table_tokens[line])
            continue
        fence = re.match(r"^\s*```\s*([\w+-]*)\s*$", line)
        if display_delimiter is not None:
            display_lines.append(line)
            closing = "\\]" if display_delimiter == "\\[" else "$$"
            if closing in line:
                raw_block = "\n".join(display_lines)
                body_lines = display_lines[:]
                body_lines[0] = body_lines[0].split(display_delimiter, 1)[1]
                body_lines[-1] = body_lines[-1].rsplit(closing, 1)[0]
                body = "\n".join(body_lines).strip()
                output.append(_line_element(raw_block, f'<div class="formula formula-display" data-latex="{html.escape(body, quote=True)}" data-display="1" title="单击选中公式">{latex_to_mathml(body, display=True)}</div>', "formula-line"))
                display_lines = []
                display_delimiter = None
            continue
        if fence:
            if in_code:
                flush_code()
                code_lines = []
                code_language = ""
                in_code = False
            else:
                in_code = True
                code_language = fence.group(1)
            continue
        if in_code:
            code_lines.append(line)
            continue
        # Display formulas are often emitted over several lines. Treat a
        # standalone opening delimiter as one selectable rendered block.
        opening = re.match(r"^\s*(\\\[|\$\$)\s*$", line)
        if opening:
            display_delimiter = opening.group(1)
            display_lines = [line]
            continue
        if not line.strip():
            output.append('<div class="md-spacer"></div>')
            continue
        heading = re.match(r"^\s*(#{1,6})\s+(.+?)\s*$", line)
        if heading:
            level = len(heading.group(1))
            output.append(_line_element(line, f'<h{level}>{render_inline_html(heading.group(2))}</h{level}>', f"heading heading-{level}"))
            continue
        if re.match(r"^\s*([-*_])(?:\s*\1){2,}\s*$", line):
            output.append('<hr class="md-rule">')
            continue
        bullet = re.match(r"^(\s*)([-+*]|\d+[.)])\s+(.+)$", line)
        if bullet:
            marker = html.escape(bullet.group(2))
            body = f'<span class="list-marker">{marker}</span>{render_inline_html(bullet.group(3))}'
            output.append(_line_element(line, body, "list-item"))
            continue
        quote = re.match(r"^\s*>\s?(.*)$", line)
        if quote:
            output.append(_line_element(line, f'<span class="quote-bar"></span>{render_inline_html(quote.group(1))}', "quote"))
            continue
        output.append(_line_element(line, render_inline_html(line)))
    if in_code:
        flush_code()
    return "".join(output)


def web_messages_for_path(path: Path | None) -> list[dict[str, str]]:
    if path is None or not path.exists():
        return []
    if path.suffix.lower() == ".jsonl":
        return parse_jsonl_messages(path)
    return [{"role": "assistant", "label": "内容", "text": clean_message_text(path.read_text(encoding="utf-8", errors="replace")), "timestamp": ""}]


def _web_payload(path: Path | None) -> dict:
    messages = []
    for index, message in enumerate(web_messages_for_path(path)):
        raw = message.get("text", "")
        messages.append({
            "id": index,
            "role": message.get("role", "assistant"),
            "label": message.get("label", "Codex"),
            "timestamp": message.get("timestamp", ""),
            "raw": raw,
            "html": render_markdown_html(raw),
        })
    return {
        "title": "Codex MarkDone",
        "path": str(path) if path else "",
        "messages": messages,
    }


def start_web_reader(initial: Path | None) -> int:
    """Serve the rich reader on localhost and open it in the default browser."""
    web_root = Path(__file__).resolve().parent.parent / "web"
    index_path = web_root / "index.html"
    js_path = web_root / "app.js"
    css_path = web_root / "styles.css"
    if not index_path.exists():
        raise FileNotFoundError(f"缺少 Web Reader 资源：{index_path}")
    payload = _web_payload(initial)

    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = "CodexMarkDone/0.2"

        def _send(self, content: bytes, content_type: str, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            route = urlparse(self.path).path
            if route in {"/", "/index.html"}:
                template = index_path.read_text(encoding="utf-8")
                state = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
                self._send(template.replace("__INITIAL_STATE__", state).encode("utf-8"), "text/html; charset=utf-8")
            elif route == "/app.js":
                self._send(js_path.read_bytes(), "text/javascript; charset=utf-8")
            elif route == "/styles.css":
                self._send(css_path.read_bytes(), "text/css; charset=utf-8")
            elif route == "/state":
                fresh = json.dumps(_web_payload(initial), ensure_ascii=False).encode("utf-8")
                self._send(fresh, "application/json; charset=utf-8")
            elif route == "/health":
                self._send(b"ok", "text/plain; charset=utf-8")
            else:
                self._send(b"not found", "text/plain; charset=utf-8", 404)

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
            if urlparse(self.path).path != "/clipboard":
                self._send(b"not found", "text/plain; charset=utf-8", 404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                request = json.loads(self.rfile.read(length).decode("utf-8"))
                mode = str(request.get("mode", "word"))
                plain = str(request.get("plain", ""))
                raw = str(request.get("raw", plain))
                fragment = str(request.get("html", ""))
                if mode == "obsidian":
                    copy_markdown(raw)
                elif mode == "formula":
                    body = str(request.get("formula", raw)).strip()
                    set_windows_clipboard(body, mathml=latex_to_mathml(body, display=True))
                elif mode == "word":
                    if fragment:
                        set_windows_clipboard(plain or raw, rich_html=cf_html(fragment))
                    else:
                        copy_word(raw or plain)
                else:
                    set_windows_clipboard(plain or raw)
                self._send(b'{"ok":true}', "application/json; charset=utf-8")
            except Exception as exc:  # report to UI without terminating server
                error = json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False).encode("utf-8")
                self._send(error, "application/json; charset=utf-8", 500)

        def log_message(self, _format: str, *_args) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}/"
    webbrowser.open_new_tab(url)
    server.serve_forever()
    return 0


class Reader(tk.Tk):
    def __init__(self, initial: Path | None = None):
        super().__init__()
        self.title("Codex MarkDone — 选择复制")
        self.geometry("1100x760")
        self.minsize(760, 500)
        self._build_ui()
        if initial:
            self.load_path(initial)

    def _build_ui(self):
        toolbar = ttk.Frame(self, padding=8)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="打开文件", command=self.open_file).pack(side="left", padx=3)
        ttk.Button(toolbar, text="会话列表", command=self.choose_session).pack(side="left", padx=3)
        ttk.Button(toolbar, text="粘贴内容", command=self.paste_clipboard).pack(side="left", padx=3)
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(toolbar, text="复制 Obsidian", command=self.copy_obsidian).pack(side="left", padx=3)
        ttk.Button(toolbar, text="复制到 Word", command=self.copy_to_word).pack(side="left", padx=3)
        ttk.Button(toolbar, text="复制公式", command=self.copy_formula).pack(side="left", padx=3)
        self.status = tk.StringVar(value="打开 Codex JSONL 或 Markdown 文件，然后在下方选择内容")
        ttk.Label(self, textvariable=self.status, padding=(10, 0, 10, 5)).pack(fill="x")
        frame = ttk.Frame(self, padding=(8, 0, 8, 8))
        frame.pack(fill="both", expand=True)
        self.text = tk.Text(frame, wrap="word", undo=False, font=("Consolas", 11), padx=12, pady=12)
        scroll = ttk.Scrollbar(frame, command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    def load_path(self, path: Path):
        try:
            content = parse_jsonl(path) if path.suffix.lower() == ".jsonl" else path.read_text(encoding="utf-8", errors="replace")
            self.text.delete("1.0", "end")
            self.text.insert("1.0", content)
            self.status.set(f"已打开：{path}")
        except Exception as exc:
            messagebox.showerror("打开失败", str(exc))

    def open_file(self):
        filename = filedialog.askopenfilename(filetypes=[("Codex/Markdown", "*.jsonl *.md *.markdown *.txt"), ("所有文件", "*.*")])
        if filename:
            self.load_path(Path(filename))

    def choose_session(self):
        files = find_session_files()
        if not files:
            messagebox.showinfo("没有会话", "没有找到本地 Codex JSONL 会话。")
            return
        dialog = tk.Toplevel(self)
        dialog.title("选择 Codex 会话")
        dialog.geometry("850x420")
        listbox = tk.Listbox(dialog, font=("Consolas", 10))
        listbox.pack(fill="both", expand=True, padx=8, pady=8)
        for path in files[:200]:
            listbox.insert("end", str(path))
        def load_selected(_event=None):
            selection = listbox.curselection()
            if selection:
                self.load_path(files[selection[0]])
                dialog.destroy()
        listbox.bind("<Double-Button-1>", load_selected)
        ttk.Button(dialog, text="打开", command=load_selected).pack(pady=(0, 8))

    def paste_clipboard(self):
        try:
            value = self.clipboard_get()
            self.text.delete("1.0", "end")
            self.text.insert("1.0", value)
            self.status.set("已粘贴剪贴板文本")
        except tk.TclError:
            messagebox.showwarning("粘贴失败", "剪贴板中没有可读取的纯文本。")

    def selection(self) -> str:
        try:
            return self.text.get("sel.first", "sel.last")
        except tk.TclError:
            return self.text.get("1.0", "end-1c")

    def copy_obsidian(self):
        try:
            copy_markdown(self.selection())
            self.status.set("已复制 Obsidian Markdown")
        except Exception as exc:
            messagebox.showerror("复制失败", str(exc))

    def copy_to_word(self):
        try:
            copy_word(self.selection())
            self.status.set("已复制 Word 内容；请在 Word 中 Ctrl+V")
        except Exception as exc:
            messagebox.showerror("复制失败", str(exc))

    def copy_formula(self):
        try:
            copy_word(self.selection(), formula_only=True)
            self.status.set("已复制 Word 可编辑公式")
        except Exception as exc:
            messagebox.showerror("公式复制失败", str(exc))


def main() -> int:
    # Keep the plugin command compatible while using the new standalone reader.
    if '--native' not in sys.argv and '--list' not in sys.argv and '--file' not in sys.argv:
        import subprocess
        program = Path.home() / 'AppData/Local/Programs/CodexMarkDone/CodexMarkDone.exe'
        command = [str(program)] if program.exists() else [sys.executable, str(Path(__file__).with_name('reader_service.py'))]
        subprocess.Popen(command + (['--current'] if '--current' in sys.argv else []), creationflags=0x08000000)
        return 0
    parser = argparse.ArgumentParser(description="Codex MarkDone local transcript reader")
    parser.add_argument("--file", type=Path, help="打开一个 Codex JSONL/Markdown 文件")
    parser.add_argument("--current", action="store_true", help="打开启动本程序的当前 Codex 任务")
    parser.add_argument("--native", action="store_true", help="使用旧版 Tk 文本窗口（兼容模式）")
    parser.add_argument("--web", action="store_true", help="在浏览器打开渲染版 Reader（默认）")
    parser.add_argument("--list", action="store_true", help="列出本地 Codex JSONL 会话")
    args = parser.parse_args()
    if args.list:
        for path in find_session_files():
            print(path)
        return 0
    initial = args.file
    if initial is None:
        # When launched by a Codex skill, this automatically resolves the
        # conversation that contains the user's request. --current makes the
        # intent explicit, while the implicit path keeps normal invocation
        # convenient inside Codex and remains blank in a regular shell.
        initial = find_current_session() if args.current or os.environ.get("CODEX_THREAD_ID") or os.environ.get("CODEX_SESSION_ID") else None
    if args.native:
        Reader(initial).mainloop()
        return 0
    # The browser reader is the default: it provides rendered Markdown,
    # message cards, line/formula selection, and a local clipboard bridge.
    return start_web_reader(initial)


if __name__ == "__main__":
    raise SystemExit(main())
