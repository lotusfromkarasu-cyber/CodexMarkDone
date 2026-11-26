"""Standalone, read-only Codex reader. All mutable state belongs to this app."""
import argparse
import ctypes
import hashlib
import http.server
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import io
import sqlite3
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from codex_markdone import set_windows_clipboard, cf_html

ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
HOME = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
if sys.platform == 'win32':
    DATA = Path.home() / 'AppData' / 'Local' / 'CodexMarkDone'
else:
    DATA = Path.home() / 'Library' / 'Application Support' / 'CodexMarkDone'

IMAGE_MIME_TYPES = {
    '.apng': 'image/apng',
    '.avif': 'image/avif',
    '.bmp': 'image/bmp',
    '.gif': 'image/gif',
    '.ico': 'image/x-icon',
    '.jpeg': 'image/jpeg',
    '.jpg': 'image/jpeg',
    '.png': 'image/png',
    '.svg': 'image/svg+xml',
    '.tif': 'image/tiff',
    '.tiff': 'image/tiff',
    '.webp': 'image/webp',
}
MAX_LOCAL_IMAGE_BYTES = 32 * 1024 * 1024
VERSION = '0.2.3'
BUILD = '20261126-sidebar'

def rollout_path(path):
    """Codex keeps the canonical JSONL path in SQLite after compression."""
    path = Path(path)
    plain = Path(str(path)[:-4]) if str(path).endswith('.zst') else path
    for candidate in (plain, Path(str(plain) + '.zst')):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError('会话记录不存在（含压缩记录）：' + str(plain))

def open_rollout(path):
    if str(path).endswith('.zst'):
        import zstandard
        return io.BufferedReader(zstandard.ZstdDecompressor().stream_reader(
            open(path, 'rb'), closefd=True))
    return open(path, 'rb')

def local_image_path(value):
    """Resolve an absolute Windows/file URL to an existing image file."""
    raw = str(value or '').strip()
    if not raw:
        return None
    if raw.lower().startswith('file:'):
        parsed = urllib.parse.urlsplit(raw)
        if parsed.netloc and parsed.netloc.lower() not in ('localhost', '127.0.0.1'):
            raw = '\\\\' + parsed.netloc + urllib.parse.unquote(parsed.path)
        else:
            raw = urllib.parse.unquote(parsed.path)
            if re.match(r'^/[A-Za-z]:[\\/]', raw):
                raw = raw[1:]
    else:
        raw = urllib.parse.unquote(raw)
        if not (re.match(r'^[A-Za-z]:[\\/]', raw) or raw.startswith('\\') or Path(raw).is_absolute()):
            return None
    try:
        path = Path(raw).resolve(strict=True)
        if not path.is_file() or path.suffix.lower() not in IMAGE_MIME_TYPES:
            return None
        if path.stat().st_size > MAX_LOCAL_IMAGE_BYTES:
            return None
        return path
    except (OSError, RuntimeError, ValueError):
        return None

def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default

def clean(text):
    # Decode annotation JSON separately; never interpret its instruction prose.
    match = re.search(r'<response-annotations>\s*([\s\S]*?)\s*</response-annotations>', text)
    if match:
        try:
            items = json.loads(match.group(1))
            blocks = []
            for item in items:
                quote = str(item.get('text', ''))
                comment = str(item.get('comment', ''))
                blocks.append('> 引用\n>\n' + '\n'.join('> ' + x for x in quote.splitlines()) + ('\n\n' + comment if comment else ''))
            prefix = text[:match.start()]
            header = re.search(r'(?im)^#{0,6}\s*Response annotations:', prefix)
            if header:
                prefix = prefix[:header.start()]
            text = prefix + '\n\n'.join(blocks) + '\n\n' + text[match.end():]
        except (ValueError, TypeError, AttributeError):
            text = text[:match.start()] + '\n[批注暂时无法解析]\n' + text[match.end():]
    for tag in ('in-app-browser-context', 'environment_context', 'oai-mem-citation', 'recommended_plugins'):
        text = re.sub(r'<' + tag + r'\b[^>]*>[\s\S]*?</' + tag + r'>', '', text, flags=re.I)
    text = re.sub(r'(?ms)^# Files mentioned by the user:.*?(?=^## My request:)', '', text)
    text = re.sub(r'(?m)^## My request:\s*', '', text)
    text = re.sub(r'(?is)</?image\b[^>]*>', '', text)
    return text.strip()

def message(obj):
    p = obj.get('payload', obj)
    if not isinstance(p, dict):
        return None
    role = p.get('role')
    if role not in ('user', 'assistant') or p.get('type', 'message') != 'message':
        return None
    if p.get('channel') in ('analysis', 'summary'):
        return None
    meta = p.get('internal_chat_message_metadata_passthrough') or {}
    if any(k in ('agents_md.instructions', 'environments.environment_context') for k in meta.get('content_item_kinds', [])):
        return None
    content = p.get('content', [])
    images = []
    if isinstance(content, str):
        text = content
    else:
        text_parts = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get('type') in ('input_text', 'output_text', 'text', None):
                text_parts.append(item.get('text', ''))
            elif item.get('type') in ('input_image', 'output_image'):
                image_url = item.get('image_url') or item.get('url')
                if isinstance(image_url, str) and re.match(r'^data:image/[a-z0-9.+-]+;base64,', image_url, re.I):
                    images.append(image_url)
        text = '\n'.join(text_parts)
    if text.lstrip().startswith('# AGENTS.md instructions'):
        return None
    if role == 'user' and re.match(r'^\s*<(?:subagent_notification|turn_aborted|external_codex_apps_writing_block_edits)\b', text):
        return None
    text = clean(text)
    if not text and not images:
        return None
    return {'role': role, 'raw': text, 'images': images, 'source_id': p.get('id') or p.get('message_id'), 'timestamp': obj.get('timestamp', ''), 'channel': p.get('channel', '')}

class Transcript:
    def __init__(self, path):
        self.path = Path(path)
        self.offset = 0
        self.pending = b''
        self.items = []
        self.stamp = None
        self.revision = 0
        self.meta = {}

    def update(self):
        physical = rollout_path(self.path)
        st = physical.stat()
        stamp = (st.st_size, st.st_mtime_ns, str(physical))
        if stamp == self.stamp:
            return
        compressed = str(physical).endswith('.zst')
        if compressed or (self.stamp and self.stamp[2] != str(physical)) or st.st_size < self.offset or (self.stamp and st.st_size == self.offset):
            self.offset, self.pending, self.items = 0, b'', []
            self.meta = {}
        with open_rollout(physical) as f:
            if not compressed:
                f.seek(self.offset)
            self._read_lines(f)
            self.offset = f.tell() if not compressed else st.st_size
        self.stamp = stamp
        self.revision += 1

    def _read_lines(self, stream):
        for line in stream:
            line = self.pending + line
            self.pending = b''
            if not line.endswith(b'\n'):
                self.pending = line
                break
            try:
                obj = json.loads(line)
                if obj.get('type') == 'session_meta':
                    self.meta = obj.get('payload', {})
                item = message(obj)
            except (ValueError, TypeError, AttributeError):
                continue
            if item:
                if self.items and all(self.items[-1].get(k) == item.get(k) for k in ('raw', 'role', 'timestamp')):
                    continue
                item['ordinal'] = obj.get('ordinal')
                item['id'] = str(len(self.items))
                self.items.append(item)

class Library:
    def __init__(self, home=HOME):
        self.home = home
        self.lock = threading.RLock()
        self.cache = {}
        self.catalog = {'projects': [], 'threads': [], 'revision': ''}
        self._idx_key = None
        self._idx_cache = None
        self._title_cache = {}

    @staticmethod
    def _norm(path):
        """Normalize a Windows path for comparison, ignoring the \\?\\ prefix."""
        p = str(path)
        if p.startswith('\\\\?\\'):
            p = p[4:]
        return os.path.normcase(os.path.normpath(p))

    @staticmethod
    def _leaf(path):
        return Library._norm(path).rstrip('/\\').split('\\')[-1]


    @staticmethod
    def _short(s, n=120):
        s = re.sub(r'\s+', ' ', str(s)).strip()
        return s if len(s) <= n else s[:n-1].rstrip() + '…'

    @staticmethod
    def _clean_title(s):
        # A task continued from another device starts with its codex:// link.
        s = re.sub(r'(?i)^codex://(?:threads|tasks)/[0-9a-f-]{36}\s*', '', str(s or ''))
        # Markdown links: keep the label, drop the URL.
        s = re.sub(r'!?\[([^\]]*)\]\([^)]*\)', r'\1', s)
        return re.sub(r'\s+', ' ', s).strip()

    def _fallback_title(self, path):
        try:
            path = rollout_path(path)
            st = path.stat()
        except OSError:
            return ''
        key = (str(path), st.st_size, st.st_mtime_ns)
        if key in self._title_cache:
            return self._title_cache[key]
        title = ''
        head = b''
        try:
            with open_rollout(path) as f:
                head = f.read(512 * 1024)
        except OSError:
            pass
        for line in head.split(b'\n'):
            try:
                obj = json.loads(line)
            except (ValueError, TypeError):
                continue
            item = message(obj)
            if not item or not item['raw'].strip():
                continue
            # Prefer the first user message; otherwise fall back to the first
            # visible assistant message (subagent sessions have no user text).
            if title and item['role'] != 'user':
                continue
            raw = re.sub(r'\s+', ' ', item['raw']).lstrip('#>*-` \t')
            if raw:
                title = raw[:56]
                if item['role'] == 'user':
                    break
        if not title:
            m = re.search(r'rollout-(\d{4}-\d{2}-\d{2})T(\d{2})-(\d{2})', str(path))
            if m:
                title = '\u4f1a\u8bdd ' + m.group(1) + ' ' + m.group(2) + ':' + m.group(3)
        self._title_cache[key] = title
        return title

    def _index_key(self):
        parts = []
        for name in ('state_5.sqlite', 'state_5.sqlite-wal', '.codex-global-state.json',
                     'sqlite/codex.db', 'sqlite/codex.db-wal', 'sqlite/codex-dev.db', 'sqlite/codex-dev.db-wal'):
            p = self.home / name
            try:
                st = p.stat()
                parts.append((name, st.st_size, st.st_mtime_ns))
            except OSError:
                parts.append((name, 0, 0))
        return tuple(parts)

    def index(self):
        with self.lock:
            _key = self._index_key()
            if _key == self._idx_key and self._idx_cache is not None:
                return self._idx_cache
            db = self.home / 'state_5.sqlite'
            connection = None
            try:
                connection = sqlite3.connect(db.as_uri() + '?mode=ro', uri=True, timeout=1)
                connection.row_factory = sqlite3.Row
                projects = [dict(x) for x in connection.execute('SELECT id,name,position FROM projects ORDER BY position')]
                columns = {r['name'] for r in connection.execute('PRAGMA table_info(threads)')}
                extra = ''.join(',' + key for key in ('thread_source', 'attached_thread_parent_id') if key in columns)
                select = ("SELECT id,coalesce(nullif(name,''),title) as title,first_user_message,rollout_path,project_id,cwd,is_pinned,archived,section_position,recency_at_ms,updated_at_ms"
                          + extra)
                threads = [dict(x) for x in connection.execute(select + " FROM threads ORDER BY recency_at_ms DESC,updated_at_ms DESC")]
                if 'thread_source' in columns:
                    # Subagent and guardian-review sessions are internal helper
                    # conversations, not standalone Codex conversations.
                    threads = [t for t in threads if t['thread_source'] not in ('subagent', 'guardian_review')]
                roots = [dict(x) for x in connection.execute('SELECT project_id,path FROM project_roots ORDER BY position')]
            except sqlite3.Error:
                # No local Codex data on this machine yet: show an empty library.
                if connection is not None:
                    connection.close()
                return {'projects': [], 'threads': [], 'revision': '', 'empty': True}
            finally:
                if connection is not None:
                    connection.close()
            state = read_json(self.home / '.codex-global-state.json', {})
            pinned_threads = state.get('pinned-thread-ids', []) or []
            projects, aliases, root_candidates = self._sidebar_projects(state, projects, roots)
            assignments = state.get('thread-project-assignments', {}) or {}
            projectless = set(state.get('projectless-thread-ids', []) or [])
            catalog = self._desktop_threads()

            # Codex Desktop publishes its sidebar display titles in its own
            # catalog database. Prefer those so names match the Codex sidebar
            # exactly; cloud (chatgpt) conversations are never shown.
            for t in threads:
                entry = catalog.get(t['id'], {})
                catalog_title = entry.get('display_title')
                title = catalog_title or (t.get('title') or '').strip()
                if not title:
                    title = (t.get('first_user_message') or '').strip()
                if not title:
                    title = self._fallback_title(t['rollout_path'])
                    if not title:
                        title = '未命名对话'
                t['title'] = self._short(title if catalog_title else self._clean_title(title))
                row = assignments.get(t['id']) or {}
                pid = aliases.get(row.get('projectId')) if row.get('projectKind') == 'local' else None
                if not pid and t['id'] not in projectless:
                    pid = aliases.get(entry.get('project_id')) or aliases.get(t.get('project_id'))
                    if not pid and not row and not t.get('attached_thread_parent_id'):
                        cwd = self._norm(t.get('cwd') or '')
                        pid = next((p for root, p in root_candidates
                                    if cwd == root or cwd.startswith(root + os.sep)), None)
                t['project_id'] = pid
                t['is_pinned'] = bool(t['is_pinned'] or t['id'] in pinned_threads)
                t['pin_order'] = pinned_threads.index(t['id']) if t['id'] in pinned_threads else t['section_position']

            by_id = {t['id']: t for t in threads}
            for t in threads:
                parent = by_id.get(t.get('attached_thread_parent_id'))
                seen = {t['id']}
                while parent and parent['id'] not in seen:
                    seen.add(parent['id'])
                    if parent['project_id']:
                        t['project_id'] = parent['project_id']
                        break
                    parent = by_id.get(parent.get('attached_thread_parent_id'))
                if t.get('attached_thread_parent_id'):
                    t['is_pinned'] = False
            payload = {'projects': projects, 'threads': threads}
            payload['revision'] = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
            self.catalog = payload
            self._idx_key = _key
            self._idx_cache = payload
            return payload

    def _desktop_threads(self):
        catalog = {}
        for name in ('codex.db', 'codex-dev.db'):
            path = self.home / 'sqlite' / name
            try:
                db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=1)
                db.row_factory = sqlite3.Row
                try:
                    cols = {r['name'] for r in db.execute('PRAGMA table_info(local_thread_catalog)')}
                    if not {'thread_id', 'display_title', 'source_kind'} <= cols:
                        continue
                    select = 'thread_id,display_title' + (',project_id' if 'project_id' in cols else '')
                    where = "source_kind!='chatgpt'" + (" AND host_id='local'" if 'host_id' in cols else '')
                    for row in db.execute('SELECT ' + select + ' FROM local_thread_catalog WHERE ' + where):
                        catalog.setdefault(row['thread_id'], dict(row))
                finally:
                    db.close()
            except (OSError, sqlite3.Error):
                pass
            if catalog:
                break
        return catalog

    def _sidebar_projects(self, state, server_projects, roots):
        server_roots = {}
        for row in roots:
            server_roots.setdefault(row['project_id'], set()).add(self._norm(row['path']))
        registry = state.get('local-projects')
        if registry is None:
            registry = {p['id']: {'name': p['name'], 'rootPaths': server_roots.get(p['id'], [])}
                        for p in server_projects}

        projects, aliases, candidates = {}, {}, []
        for pid, row in registry.items():
            paths = {self._norm(r) for r in row.get('rootPaths', [])}
            if pid.startswith('g-p-') or any('.chatgpt-projects' in r for r in paths):
                continue
            projects[pid] = {'id': pid, 'name': row.get('name') or pid, 'is_pinned': False}
            aliases[pid] = pid
            candidates.extend((r, pid) for r in paths)
            for server_id, sr in server_roots.items():
                if paths and sr == paths:
                    aliases.setdefault(server_id, pid)
        mappings = state.get('app-server-project-id-by-legacy-project-id-by-host', {}) or {}
        local = self._norm(self.home)
        for host, mapping in mappings.items():
            if host != 'local' and not (host.startswith('local:') and self._norm(host[6:]) == local):
                continue
            for legacy, server in mapping.items():
                if legacy in projects and server in server_roots:
                    aliases[server] = legacy

        atoms = next((v for k, v in state.items() if k.startswith('electron-owner-atoms')
                      and isinstance(v, dict) and 'unified-sidebar-project-order-v1' in v), {})
        def ids(items):
            return list(dict.fromkeys(aliases[p] for key in items
                        if (p := key.removeprefix('codex:project:')) in aliases))
        pins = ids(state.get('pinned-project-ids', []) or [])
        pin_order = [p for p in ids(atoms.get('unified-sidebar-pinned-order-v1', [])) if p in pins]
        pin_order += [p for p in pins if p not in pin_order]
        order = list(dict.fromkeys(pin_order + ids(atoms.get('unified-sidebar-project-order-v1', []))
                                  + ids(state.get('project-order', []) or []) + list(projects)))
        for position, p in enumerate(order):
            projects[p].update(position=position, is_pinned=p in pins,
                               pin_order=pin_order.index(p) if p in pins else None)
        return [projects[p] for p in order], aliases, sorted(candidates, key=lambda r: -len(r[0]))

    def _reference_path(self, reference):
        # history_base.thread_id is a physical rollout ID, not necessarily a
        # sidebar thread ID. Match the filename suffix, not any UUID inside it.
        candidates = []
        for folder in ('sessions', 'archived_sessions'):
            root = self.home / folder
            for separator in ('-', '_'):
                candidates.extend(root.glob('**/*' + separator + reference + '.jsonl'))
                candidates.extend(root.glob('**/*' + separator + reference + '.jsonl.zst'))
        if candidates:
            return rollout_path(max(candidates, key=lambda p: p.stat().st_mtime_ns))
        row = next((x for x in self.catalog['threads'] if x['id'] == reference), None)
        if row:
            return rollout_path(row['rollout_path'])
        raise FileNotFoundError('找不到前序历史记录：' + reference)

    def _history(self, tid, before=None, visiting=None, source=None):
        visiting = set() if visiting is None else visiting
        row = next((x for x in self.catalog['threads'] if x['id'] == tid), None)
        physical = rollout_path(source or (row['rollout_path'] if row else self._reference_path(tid)))
        key = str(physical)
        if key in visiting:
            raise ValueError('分叉会话历史存在循环')
        visiting = visiting | {key}
        if key not in self.cache:
            self.cache[key] = Transcript(physical)
        t = self.cache[key]
        t.update()
        inherited = []
        base = t.meta.get('history_base') or {}
        parent = t.meta.get('forked_from_id')
        cutoff = t.meta.get('forked_from_ordinal_exclusive')
        if base.get('thread_id') and base.get('end_ordinal_exclusive') is not None:
            cutoff = base['end_ordinal_exclusive']
            reference = base['thread_id']
            inherited = self._history(reference, min(before, cutoff) if before is not None else cutoff,
                                      visiting, self._reference_path(reference))
        elif parent and cutoff is not None:
            inherited = self._history(parent, min(before, cutoff) if before is not None else cutoff, visiting)
        own = [dict(m) for m in t.items if before is None or (m.get('ordinal') is not None and m['ordinal'] < before)]
        # Some older forks copied the prefix into their own file.
        known = {m['source_id'] for m in inherited if m.get('source_id')}
        return inherited + [m for m in own if not m.get('source_id') or m['source_id'] not in known]

    def transcript(self, tid):
        with self.lock:
            self.index()
            items = self._history(tid)
            for i, item in enumerate(items):
                item['id'] = str(i)
            row = next(x for x in self.catalog['threads'] if x['id'] == tid)
            revision = hashlib.sha256(json.dumps(items, sort_keys=True).encode()).hexdigest()[:16]
            current_key = str(rollout_path(row['rollout_path']))
            t = self.cache[current_key]
            result = {'id': tid, 'title': row['title'], 'revision': revision,
                      'mtime': t.stamp[1] if t.stamp else 0, 'messages': items}
            while len(self.cache) > 12:
                self.cache.pop(next(k for k in self.cache if k != current_key))
            return result

def make_server(library, port=0):
    token = secrets.token_urlsafe(32)
    class Handler(http.server.BaseHTTPRequestHandler):
        def send(self, data, kind='application/json; charset=utf-8', status=200, cache='no-store'):
            if not isinstance(data, bytes):
                data = json.dumps(data, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', cache)
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: http: https:; font-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}':
                return self.send({'error':'Invalid host'}, status=403)
            u = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(u.query)
            try:
                if u.path == '/api/health':
                    return self.send({'app':'CodexMarkDone', 'version':VERSION, 'build':BUILD})
                if u.path == '/api/library':
                    return self.send(library.index())
                if u.path == '/api/thread':
                    tid = q.get('id', [''])[0]
                    result = library.transcript(tid)
                    if str(result['revision']) == q.get('revision', [''])[0]:
                        return self.send({'unchanged':True})
                    return self.send(result)
                if u.path == '/api/settings':
                    return self.send({'settings': read_json(DATA / 'settings.json', {}), 'token':token})
                if u.path == '/api/image':
                    image_path = local_image_path(q.get('path', [''])[0])
                    if image_path is None:
                        return self.send({'error':'Invalid or unsupported image path'}, status=400)
                    return self.send(
                        image_path.read_bytes(),
                        IMAGE_MIME_TYPES[image_path.suffix.lower()],
                        cache='private, max-age=60',
                    )
                rel = u.path.lstrip('/') or 'index.html'
                p = (ROOT / 'web' / rel).resolve()
                if not p.is_relative_to((ROOT / 'web').resolve()) or not p.is_file():
                    return self.send({'error':'Not found'}, status=404)
                cache = 'public, max-age=3600' if rel.startswith('vendor/') else 'no-store'
                return self.send(p.read_bytes(), mimetypes.guess_type(str(p))[0] or 'application/octet-stream', cache=cache)
            except Exception as exc:
                self.send({'error':str(exc)}, status=503)

        def do_POST(self):
            origin = f'http://127.0.0.1:{self.server.server_port}'
            if self.headers.get('Origin') != origin or self.headers.get('X-Reader-Token') != token:
                return self.send({'error':'Invalid origin'}, status=403)
            try:
                size = int(self.headers.get('Content-Length','0'))
                if not 0 < size <= 16 * 1024 * 1024:
                    raise ValueError('请求过大')
                req = json.loads(self.rfile.read(size))
                if self.path == '/api/settings':
                    with library.lock:
                        temp = DATA / 'settings.tmp'
                        temp.write_text(json.dumps(req, ensure_ascii=False), encoding='utf-8')
                        temp.replace(DATA / 'settings.json')
                elif self.path == '/api/clipboard':
                    with library.lock:
                        mode = req['mode']
                        if mode in ('obsidian', 'latex'):
                            set_windows_clipboard(req['raw'])
                        elif mode == 'formula':
                            import xml.etree.ElementTree as ET
                            if ET.fromstring(req['mathml']).tag != '{http://www.w3.org/1998/Math/MathML}math':
                                raise ValueError('无效 MathML')
                            set_windows_clipboard(req['raw'], mathml=req['mathml'])
                        elif mode in ('word', 'wps'):
                            if sys.platform == 'darwin':
                                fragment = req.get('html', '')
                                rich_html = '<!doctype html><html><head><meta charset="utf-8"></head><body>' + fragment + '</body></html>'
                                set_windows_clipboard(req.get('plain', ''), rich_html=rich_html)
                            else:
                                from office_copy import copy_native
                                copy_native(req['html'], mode)
                        else:
                            raise ValueError('未知复制方式')
                else:
                    return self.send({'error':'Not found'}, status=404)
                self.send({'ok':True, 'platform':sys.platform})
            except Exception as exc:
                self.send({'error':str(exc)}, status=400)

        def log_message(self, *args):
            pass
    return http.server.ThreadingHTTPServer(('127.0.0.1', port), Handler)

def main():
    DATA.mkdir(parents=True, exist_ok=True)
    parser = argparse.ArgumentParser()
    parser.add_argument('--current', action='store_true')
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    suffix = ''
    if args.current:
        tid = os.environ.get('CODEX_THREAD_ID') or os.environ.get('CODEX_SESSION_ID')
        if tid:
            suffix = '#thread=' + urllib.parse.quote(tid)
    # Serialize simultaneous launches before the port file exists.
    kernel = None
    mutex = None
    lock_file = None
    if sys.platform == 'win32':
        kernel = ctypes.windll.kernel32
        kernel.CreateMutexW.restype = ctypes.c_void_p
        mutex = kernel.CreateMutexW(None, True, 'Local\\CodexMarkDone.Reader.v2')
        already = kernel.GetLastError() == 183
    else:
        import fcntl
        lock_file = (DATA / 'reader.lock').open('a', encoding='utf-8')
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            already = False
        except BlockingIOError:
            lock_file.close()
            lock_file = None
            already = True
    if already:
        for _ in range(50):
            instance = read_json(DATA / 'instance.json', {})
            try:
                url = instance['url']
                health = json.load(urllib.request.urlopen(url + 'api/health', timeout=.5))
                if health.get('app') == 'CodexMarkDone':
                    if not args.no_browser:
                        webbrowser.open(url + suffix)
                    return
            except Exception:
                time.sleep(.1)
        raise RuntimeError('Reader 已在启动，请稍后再次打开')
    server = make_server(Library())
    url = f'http://127.0.0.1:{server.server_port}/'
    (DATA / 'instance.json').write_text(json.dumps({'url':url,'pid':os.getpid()}), encoding='utf-8')
    threading.Thread(target=server.serve_forever, daemon=True).start()
    import pystray
    from PIL import Image
    picture = Image.open(ROOT / 'web' / 'icon-64.png').convert('RGBA')
    def stop(icon, _):
        server.shutdown()
        icon.stop()
    icon = pystray.Icon('CodexMarkDone', picture, 'Codex MarkDone', pystray.Menu(
        pystray.MenuItem('打开 Reader', lambda: webbrowser.open(url), default=True),
        pystray.MenuItem('退出', stop)))
    if not args.no_browser:
        webbrowser.open(url + suffix)
    try:
        icon.run()
    finally:
        server.server_close()
        (DATA / 'instance.json').unlink(missing_ok=True)
        if kernel is not None and mutex is not None:
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel.CloseHandle(mutex)
        if lock_file is not None:
            lock_file.close()

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        if sys.platform == 'win32':
            ctypes.windll.user32.MessageBoxW(None, str(exc), 'Codex MarkDone', 0x10)
        else:
            try:
                import tkinter as tk
                from tkinter import messagebox
                root = tk.Tk()
                root.withdraw()
                messagebox.showerror('Codex MarkDone', str(exc), parent=root)
                root.destroy()
            except Exception:
                print(str(exc), file=sys.stderr)
