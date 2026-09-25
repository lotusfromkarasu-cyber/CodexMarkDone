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
DATA = Path.home() / 'AppData' / 'Local' / 'CodexMarkDone'

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
    elif re.match(r'^[A-Za-z]:[\\/]', raw) or raw.startswith('\\'):
        raw = urllib.parse.unquote(raw)
    else:
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
        st = self.path.stat()
        stamp = (st.st_size, st.st_mtime_ns)
        if stamp == self.stamp:
            return
        if st.st_size < self.offset or (self.stamp and st.st_size == self.offset):
            self.offset, self.pending, self.items = 0, b'', []
        with self.path.open('rb') as f:
            f.seek(self.offset)
            chunk = f.read()
            self.offset = f.tell()
        lines = (self.pending + chunk).split(b'\n')
        self.pending = lines.pop()
        for line in lines:
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
        self.stamp = stamp
        self.revision += 1

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
            st = Path(path).stat()
        except OSError:
            return ''
        key = (str(path), st.st_size, st.st_mtime_ns)
        if key in self._title_cache:
            return self._title_cache[key]
        title = ''
        head = b''
        try:
            with Path(path).open('rb') as f:
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
        for name in ('state_5.sqlite', 'state_5.sqlite-wal', '.codex-global-state.json'):
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
                has_ts = any(r['name'] == 'thread_source' for r in connection.execute('PRAGMA table_info(threads)'))
                select = ("SELECT id,coalesce(nullif(name,''),title) as title,first_user_message,rollout_path,project_id,cwd,is_pinned,archived,section_position,recency_at_ms,updated_at_ms"
                          + (",thread_source" if has_ts else ""))
                threads = [dict(x) for x in connection.execute(select + " FROM threads ORDER BY recency_at_ms DESC,updated_at_ms DESC")]
                if has_ts:
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
            local_projects = state.get('local-projects', {}) or {}
            assignments = state.get('thread-project-assignments', {}) or {}
            pinned_projects = state.get('pinned-project-ids', []) or []

            # Codex Desktop publishes its sidebar display titles in its own
            # catalog database. Prefer those so names match the Codex sidebar
            # exactly; cloud (chatgpt) conversations are never shown.
            catalog_titles = {}
            try:
                dev_db = self.home / 'sqlite' / 'codex-dev.db'
                dev = sqlite3.connect(dev_db.as_uri() + '?mode=ro', uri=True, timeout=1)
                try:
                    for row in dev.execute(
                            "SELECT thread_id, display_title FROM local_thread_catalog WHERE source_kind != 'chatgpt'"):
                        if row[1]:
                            catalog_titles[row[0]] = row[1]
                finally:
                    dev.close()
            except (sqlite3.Error, OSError):
                pass

            roots_by_project = {}
            for x in roots:
                roots_by_project.setdefault(x['project_id'], []).append(x['path'])
            position_of = {p['id']: i for i, p in enumerate(projects)}

            # Map Codex local-project ids (legacy UUID or local-...) to the
            # server project ids used by the projects table, matching root sets.
            lp_to_server = {}
            for lp_id, lp in local_projects.items():
                wanted = {self._norm(p) for p in (lp.get('rootPaths') or [])}
                if not wanted:
                    continue
                for pid, proots in roots_by_project.items():
                    if {self._norm(p) for p in proots} == wanted:
                        lp_to_server[lp_id] = pid
                        break

            # A ChatGPT web project is hosted under the local .chatgpt-projects
            # folder; those projects never appear in the local sidebar.
            cloud = {pid for pid, proots in roots_by_project.items()
                     if any('.chatgpt-projects' in self._norm(p) for p in proots)}

            # cwd fallback candidates: exact roots first, then leaf names.
            root_candidates = sorted(
                ((self._norm(x['path']), x['project_id']) for x in roots),
                key=lambda r: (position_of.get(r[1], 99), 0))
            leaf_to_project = {}
            for p in projects:
                leaves = {self._leaf(r) for r in roots_by_project.get(p['id'], [])}
                leaves.add(self._leaf(p['name']))
                for leaf in leaves:
                    leaf_to_project.setdefault(leaf, p['id'])

            def assign(t):
                pid = t.get('project_id')
                if pid:
                    return pid
                row = assignments.get(t['id']) or {}
                if row.get('projectKind') == 'local':
                    pid = lp_to_server.get(row.get('projectId'))
                    if pid:
                        return pid
                cwd = self._norm(t.get('cwd') or '')
                if not cwd:
                    return None
                for root, pid in root_candidates:
                    if cwd == root or cwd.startswith(root + os.sep):
                        return pid
                return leaf_to_project.get(self._leaf(cwd))

            for t in threads:
                from_catalog = t['id'] in catalog_titles
                title = catalog_titles.get(t['id']) or ''
                if not from_catalog:
                    title = (t.get('title') or '').strip()
                if not title:
                    title = (t.get('first_user_message') or '').strip()
                if not title:
                    title = self._fallback_title(t['rollout_path'])
                    if not title:
                        title = '未命名对话'
                t['title'] = self._short(title if from_catalog else self._clean_title(title))
                t['project_id'] = assign(t)
                if t['project_id'] in cloud:
                    t['project_id'] = None
                t['is_pinned'] = bool(t['is_pinned'] or t['id'] in pinned_threads)
                t['pin_order'] = pinned_threads.index(t['id']) if t['id'] in pinned_threads else t['section_position']

            # Pinned projects first, in Codex pin order.
            resolved_pins = []
            for pid in pinned_projects:
                rid = pid if pid in {p['id'] for p in projects} else lp_to_server.get(pid)
                if rid and rid not in resolved_pins and rid not in cloud:
                    resolved_pins.append(rid)
            for p in projects:
                p['is_pinned'] = p['id'] in resolved_pins
                p['pin_order'] = resolved_pins.index(p['id']) if p['is_pinned'] else None
            projects = [p for p in projects if p['id'] not in cloud]
            projects.sort(key=lambda p: (0 if p['is_pinned'] else 1,
                                         p['pin_order'] if p['is_pinned'] else p['position']))
            payload = {'projects': projects, 'threads': threads}
            payload['revision'] = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
            self.catalog = payload
            self._idx_key = _key
            self._idx_cache = payload
            return payload

    def _history(self, tid, before=None, visiting=None):
        visiting = set() if visiting is None else visiting
        if tid in visiting:
            raise ValueError('分叉会话历史存在循环')
        visiting = visiting | {tid}
        row = next((x for x in self.catalog['threads'] if x['id'] == tid), None)
        if row is None:
            raise FileNotFoundError('找不到此对话的历史：' + tid)
        if tid not in self.cache or str(self.cache[tid].path) != row['rollout_path']:
            self.cache[tid] = Transcript(row['rollout_path'])
        t = self.cache[tid]
        t.update()
        inherited = []
        parent = t.meta.get('forked_from_id')
        cutoff = t.meta.get('forked_from_ordinal_exclusive')
        if parent and cutoff is not None:
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
            t = self.cache[tid]
            result = {'id': tid, 'title': row['title'], 'revision': revision,
                      'mtime': t.stamp[1] if t.stamp else 0, 'messages': items}
            while len(self.cache) > 12:
                self.cache.pop(next(k for k in self.cache if k != tid))
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
                    return self.send({'app':'CodexMarkDone', 'version':2})
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
                            from office_copy import copy_native
                            copy_native(req['html'], mode)
                        else:
                            raise ValueError('未知复制方式')
                else:
                    return self.send({'error':'Not found'}, status=404)
                self.send({'ok':True})
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
    # A named mutex serializes simultaneous launches before the port file exists.
    kernel = ctypes.windll.kernel32
    kernel.CreateMutexW.restype = ctypes.c_void_p
    mutex = kernel.CreateMutexW(None, True, 'Local\\CodexMarkDone.Reader.v2')
    already = kernel.GetLastError() == 183
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
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle(mutex)

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        ctypes.windll.user32.MessageBoxW(None, str(exc), 'Codex MarkDone', 0x10)
