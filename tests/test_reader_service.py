import gc
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from reader_service import Transcript, clean, message, Library

class ReaderTests(unittest.TestCase):
    def test_incremental_partial_record(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'session.jsonl'
            row = json.dumps({'payload': {'role': 'assistant', 'type': 'message', 'content': [{'type': 'output_text', 'text': r'\[a \\ b\]'}]}}).encode()
            path.write_bytes(row[:20])
            transcript = Transcript(path)
            transcript.update()
            self.assertEqual(transcript.items, [])
            with path.open('ab') as stream:
                stream.write(row[20:] + b'\n')
            transcript.update()
            self.assertEqual(transcript.items[0]['raw'], r'\[a \\ b\]')
            transcript.update()
            self.assertEqual(len(transcript.items), 1)

    def test_annotations(self):
        raw = 'Response annotations:\nInternal instructions\n<response-annotations>' + json.dumps([{'text': r'\hat S', 'source': {'messageId': 'private'}}]) + '</response-annotations>\n真实问题'
        result = clean(raw)
        self.assertIn(r'\hat S', result)
        self.assertIn('真实问题', result)
        self.assertNotIn('private', result)
        self.assertNotIn('Internal', result)

    def test_internal_messages(self):
        self.assertIsNone(message({'payload': {'role': 'assistant', 'channel': 'analysis', 'content': 'hidden'}}))
        self.assertIsNone(message({'payload': {'role': 'tool', 'content': 'hidden'}}))

    def test_clean_title(self):
        self.assertEqual(Library._clean_title('codex://threads/00000000-0000-4000-8000-000000000001 示例会话'), '示例会话')
        self.assertEqual(Library._clean_title('[$ExampleSkill](C:\\Users\\Example\\.codex\\skills\\example-skill\\SKILL.md) upgrade'), '$ExampleSkill upgrade')
        self.assertEqual(Library._clean_title('  a\n\t b '), 'a b')
        self.assertEqual(Library._clean_title('[x](http://example.com) 文案'), 'x 文案')

    def test_transcript_mtime(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'session.jsonl'
            row = json.dumps({'payload': {'role': 'user', 'type': 'message', 'content': [{'type': 'input_text', 'text': 'hi'}]}}).encode()
            path.write_bytes(row + b'\n')
            transcript = Transcript(path)
            transcript.update()
            self.assertIsNotNone(transcript.stamp)
            transcript.update()
            self.assertEqual(transcript.revision, 1)
            self.assertGreater(transcript.stamp[1], 0)

if __name__ == '__main__':
    unittest.main()

class LibraryIndexTests(unittest.TestCase):
    """Project assignment, cloud exclusion and pinning mirror the Codex sidebar."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.db = db = sqlite3.connect(self.home / 'state_5.sqlite')
        db.executescript("CREATE TABLE projects(id TEXT PRIMARY KEY, name TEXT NOT NULL, metadata TEXT NOT NULL DEFAULT '{}', position INTEGER NOT NULL, created_at_ms INTEGER NOT NULL DEFAULT 0, updated_at_ms INTEGER NOT NULL DEFAULT 0);CREATE TABLE project_roots(project_id TEXT NOT NULL, position INTEGER NOT NULL, path TEXT NOT NULL, PRIMARY KEY(project_id, position));CREATE TABLE thread_sections(id TEXT PRIMARY KEY, name TEXT NOT NULL, appearance TEXT);CREATE TABLE threads(id TEXT PRIMARY KEY, rollout_path TEXT NOT NULL, created_at INTEGER NOT NULL DEFAULT 0, updated_at INTEGER NOT NULL DEFAULT 0, source TEXT NOT NULL DEFAULT '', model_provider TEXT NOT NULL DEFAULT '', cwd TEXT NOT NULL, title TEXT NOT NULL, sandbox_policy TEXT NOT NULL DEFAULT '', approval_mode TEXT NOT NULL DEFAULT '', tokens_used INTEGER NOT NULL DEFAULT 0, has_user_event INTEGER NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0, archived_at INTEGER, git_sha TEXT, git_branch TEXT, git_origin_url TEXT, cli_version TEXT NOT NULL DEFAULT '', first_user_message TEXT NOT NULL DEFAULT '', agent_nickname TEXT, agent_role TEXT, memory_mode TEXT NOT NULL DEFAULT 'enabled', model TEXT, reasoning_effort TEXT, agent_path TEXT, created_at_ms INTEGER, updated_at_ms INTEGER, thread_source TEXT, preview TEXT NOT NULL DEFAULT '', recency_at INTEGER NOT NULL DEFAULT 0, recency_at_ms INTEGER NOT NULL DEFAULT 0, history_mode TEXT NOT NULL DEFAULT 'legacy', name TEXT, is_pinned INTEGER NOT NULL DEFAULT 0, thread_section_id TEXT REFERENCES thread_sections(id), section_position INTEGER, section_entered_at_ms INTEGER, project_id TEXT REFERENCES projects(id));")
        db.executemany('INSERT INTO projects VALUES(?,?,?,?,0,0)', [
            ('p-workspace', 'Workspace One', '{}', 0),
            ('p-research', 'Project Two', '{}', 1),
            ('p-cloud', 'Cloud Project', '{}', 2),
        ])
        db.executemany('INSERT INTO project_roots VALUES(?,?,?)', [
            ('p-workspace', 0, 'C:\\Projects\\WorkspaceOne'),
            ('p-research', 0, 'D:\\Projects\\Research'),
            ('p-cloud', 0, 'C:\\Users\\Example\\.codex\\.chatgpt-projects\\g-x'),
        ])
        db.executemany('INSERT INTO threads(id,rollout_path,cwd,title,recency_at_ms,updated_at_ms) VALUES(?,?,?,?,?,?)', [
            ('t-root', 'r.jsonl', '\\\\?\\C:\\Projects\\WorkspaceOne', 'root', 0, 0),
            ('t-lp', 'r.jsonl', 'C:\\Projects\\WorkspaceOne', 'assigned', 0, 0),
            ('t-leaf', 'r.jsonl', 'D:\\Projects\\Research\\Group', 'leaf', 0, 0),
            ('t-none', 'r.jsonl', 'C:\\Temp\\Unassigned', 'none', 0, 0),
            ('t-cloud', 'r.jsonl', 'C:\\Users\\Example\\.codex\\.chatgpt-projects\\g-x', 'cloud', 0, 0),
        ])
        db.commit()
        db.close()
        state = {
            'local-projects': {
                '11111111-2222-4333-8444-555555555555': {'name': 'Workspace One', 'rootPaths': ['C:\\Projects\\WorkspaceOne']},
            },
            'thread-project-assignments': {
                't-lp': {'projectKind': 'local', 'projectId': '11111111-2222-4333-8444-555555555555'},
                't-cloud': {'projectKind': 'remote', 'projectId': 'g-x'},
            },
            'pinned-project-ids': ['11111111-2222-4333-8444-555555555555'],
            'pinned-thread-ids': ['t-root'],
        }
        (self.home / '.codex-global-state.json').write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')

    def tearDown(self):
        try:
            self.db.close()
        except Exception:
            pass
        gc.collect()
        self.tmp.cleanup()

    def test_sidebar_model(self):
        data = Library(home=self.home).index()
        self.assertEqual([p['name'] for p in data['projects']], ['Workspace One', 'Project Two'])
        self.assertNotIn('p-cloud', {p['id'] for p in data['projects']})
        by_id = {t['id']: t for t in data['threads']}
        self.assertEqual(by_id['t-root']['project_id'], 'p-workspace')
        self.assertEqual(by_id['t-lp']['project_id'], 'p-workspace')
        self.assertEqual(by_id['t-leaf']['project_id'], 'p-research')
        self.assertIsNone(by_id['t-none']['project_id'])
        self.assertIsNone(by_id['t-cloud']['project_id'])
        self.assertTrue(by_id['t-root']['is_pinned'])
        self.assertEqual([p['name'] for p in data['projects'] if p['is_pinned']], ['Workspace One'])

class ForkHistoryTests(unittest.TestCase):
    def test_nested_fork_cutoff_and_parent_append(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            def write(name, rows):
                p = root / (name + '.jsonl')
                p.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
                return str(p)
            def msg(n, text):
                return {'ordinal': n, 'payload': {'type': 'message', 'role': 'user', 'id': str(n), 'content': text}}
            def meta(parent, cutoff):
                return {'type': 'session_meta', 'payload': {'forked_from_id': parent, 'forked_from_ordinal_exclusive': cutoff}}
            paths = {'a': write('a', [msg(1, 'first'), msg(5, 'second'), msg(9, 'excluded')]),
                     'b': write('b', [meta('a', 8), msg(10, 'branch')]),
                     'c': write('c', [meta('b', 5)])}
            lib = Library(root)
            lib.catalog = {'threads': [{'id': k, 'title': k, 'rollout_path': v} for k, v in paths.items()]}
            lib.index = lambda: lib.catalog
            self.assertEqual([m['raw'] for m in lib.transcript('b')['messages']], ['first', 'second', 'branch'])
            self.assertEqual([m['raw'] for m in lib.transcript('c')['messages']], ['first'])
            with open(paths['a'], 'a', encoding='utf-8') as f:
                f.write(json.dumps(msg(20, 'later')) + '\n')
            self.assertEqual([m['raw'] for m in lib.transcript('b')['messages']], ['first', 'second', 'branch'])

    def test_internal_notifications_are_not_questions(self):
        for tag in ('subagent_notification', 'turn_aborted', 'external_codex_apps_writing_block_edits'):
            self.assertIsNone(message({'payload': {'role': 'user', 'content': '<' + tag + '>internal</' + tag + '>'}}))
        self.assertEqual(message({'payload': {'role': 'user', 'content': '解释 <turn_aborted> 的含义'}})['raw'], '解释 <turn_aborted> 的含义')
