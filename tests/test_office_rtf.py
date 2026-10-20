import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from docx import Document
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from office_copy import make_document, copy_native
from office_rtf import document_rtf, escape

class OfficeRtfTests(unittest.TestCase):
    def test_editable_math_table_and_unicode(self):
        fragment = '<h2>中文标题</h2><p><b>加粗</b><math xmlns="http://www.w3.org/1998/Math/MathML"><mfrac><msup><mi>x</mi><mn>2</mn></msup><msqrt><mi>y</mi></msqrt></mfrac></math></p><table><tr><th>变量</th><th>值</th></tr><tr><td>x</td><td>1</td></tr></table>'
        stream=io.BytesIO();make_document(fragment,stream);stream.seek(0)
        rtf=document_rtf(Document(stream)).decode('ascii')
        for token in (r'\mmath',r'\*\moMath',r'\mf ',r'\mnum ',r'\mden ',r'\msSup ',r'\mrad ',r'\mdegHide on',r'\trowd',r'\cellx',r'\outlinelevel1',r'\highlight0'):
            self.assertIn(token,rtf)
        self.assertEqual(rtf.count(r'\row '),2)
        self.assertIn(escape('中文标题'),rtf)
        self.assertNotIn('mmathPict',rtf)
        depth=0
        for index,char in enumerate(rtf):
            if char not in '{}':continue
            backslashes=0;pos=index-1
            while pos>=0 and rtf[pos]=='\\':backslashes+=1;pos-=1
            if backslashes%2:continue
            depth += 1 if char=='{' else -1
            self.assertGreaterEqual(depth,0)
        self.assertEqual(depth,0)

    def test_office_copy_never_contacts_office_or_uses_tempfile(self):
        import builtins
        original=builtins.__import__
        def guarded(name,*args,**kwargs):
            if name.startswith(('pythoncom','win32com')):raise AssertionError('Office COM must not be imported')
            return original(name,*args,**kwargs)
        for target in ('word','wps'):
            with patch('builtins.__import__',side_effect=guarded), patch('codex_markdone.set_windows_clipboard') as write:
                self.assertTrue(copy_native('<p>Test</p>',target))
                self.assertTrue(write.call_args.kwargs['rtf'].startswith(b'{\\rtf1'))
                self.assertEqual(write.call_args.args[0],'Test')

    def test_unicode_surrogates_and_escape(self):
        self.assertEqual(escape('{x}\\'),r'\{x\}\\')
        self.assertEqual(escape('😀'),r'\u-10179?\u-8704?')

    def test_equations_are_italic_and_never_bold(self):
        fragment='<h2>Bold heading <math xmlns="http://www.w3.org/1998/Math/MathML"><mi mathvariant="bold">A</mi><mo>=</mo><mi mathvariant="normal">ω</mi><mi>𝐱</mi></math></h2>'
        stream=io.BytesIO();make_document(fragment,stream);stream.seek(0)
        document=Document(stream)
        ns='{http://schemas.openxmlformats.org/officeDocument/2006/math}'
        for style in document.element.xpath('.//m:r/m:rPr/m:sty'):
            self.assertEqual(style.get(ns+'val'),'i')
        self.assertNotIn('𝐱',''.join(document.element.itertext()))
        rtf=document_rtf(document).decode('ascii')
        self.assertIn(r'\mmath\b0\i',rtf)
        self.assertNotIn(r'\msty1',rtf)
        self.assertNotIn(r'\msty3',rtf)
        self.assertIn(r'\f2\b0\i\msty2',rtf)

if __name__ == '__main__':unittest.main()
