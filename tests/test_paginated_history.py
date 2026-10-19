"""History format regressions: physical rollout IDs and compressed storage."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
import zstandard
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from reader_service import Library, Transcript

def meta(n, base=None, fork=None):
    payload = {'history_base': base} if base else {}
    if fork:
        payload.update(forked_from_id=fork, forked_from_ordinal_exclusive=100)
    return {'type': 'session_meta', 'ordinal': n, 'payload': payload}

def msg(n, text):
    return {'ordinal': n, 'payload': {'role': 'user', 'type': 'message', 'content': text}}

class PaginatedTests(unittest.TestCase):
    def test_compressed_rename_and_materialization(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/'a.jsonl'
            content = (json.dumps(msg(1, 'first'))+'\n').encode()
            p.write_bytes(content)
            t = Transcript(p); t.update()
            z = Path(str(p)+'.zst')
            z.write_bytes(zstandard.ZstdCompressor().compress(content)); p.unlink()
            t.update(); self.assertEqual([m['raw'] for m in t.items], ['first'])
            p.write_bytes(content+(json.dumps(msg(2,'next'))+'\n').encode())
            t.update(); self.assertEqual([m['raw'] for m in t.items], ['first','next'])

    def test_physical_reference_chain_and_exclusive_boundary(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder); root=home/'sessions'; root.mkdir()
            def write(name, rows, compressed=False):
                p=root/name
                raw=('\n'.join(json.dumps(r) for r in rows)+'\n').encode()
                if compressed:
                    Path(str(p)+'.zst').write_bytes(zstandard.ZstdCompressor().compress(raw))
                else: p.write_bytes(raw)
                return str(p)
            def base(ref,n):return {'thread_id':ref,'end_ordinal_exclusive':n}
            write('rollout-2026-01-01T00-00-00-original.jsonl', [meta(0),msg(1,'old'),msg(5,'abandoned')],True)
            write('rollout-2026-01-02T00-00-00-original_segment.jsonl', [meta(5,base('original',5)),msg(6,'middle'),msg(9,'abandoned2')])
            current=write('rollout-2026-01-03T00-00-00-original_current.jsonl',[meta(9,base('segment',9),fork='missing-parent'),msg(10,'new')])
            lib=Library(home);lib.catalog={'threads':[{'id':'original','title':'t','rollout_path':current}]};lib.index=lambda:lib.catalog
            self.assertEqual([m['raw'] for m in lib.transcript('original')['messages']],['old','middle','new'])
            self.assertEqual([m['raw'] for m in lib.transcript('original')['messages']],['old','middle','new'])

if __name__ == '__main__': unittest.main()
