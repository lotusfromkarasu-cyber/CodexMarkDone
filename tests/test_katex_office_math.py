"""Real KaTeX fixtures: tag spacers and aligned cells aren't matrices."""
import io
import json
from pathlib import Path
import sys
import unittest
from docx import Document
from docx.oxml.ns import qn
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from office_copy import make_document
from office_rtf import document_rtf

CASES=json.loads((Path(__file__).parent/'fixtures/office_math_cases.json').read_text(encoding='utf8'))

class KatexOfficeTests(unittest.TestCase):
    def test_numbered_single_line_and_integral_hidden_limit(self):
        document=self.convert('tagged')
        self.assertEqual(len(document.element.xpath('.//m:m')),0)
        self.assertEqual(len(document.element.xpath('.//m:e[not(*)]')),0)
        self.assertIn('(2)',''.join(document.element.itertext()))
        nary=document.element.xpath('.//m:nary')[0]
        self.assertEqual(nary.find('./'+qn('m:naryPr')+'/'+qn('m:supHide')).get(qn('m:val')),'1')
        self.assertTrue(''.join(nary.find(qn('m:e')).itertext()).strip())
        self.assertIn(r'\msupHide on',document_rtf(document).decode('ascii'))

    def test_aligned_three_rows_no_spacer_placeholders(self):
        document=self.convert('aligned')
        self.assertEqual(len(document.tables),1)
        self.assertEqual(len(document.tables[0].rows),3)
        self.assertEqual(len(document.tables[0].columns),3)
        self.assertEqual(len(document.element.xpath('.//m:e[not(*)]')),0)
        self.assertIn('(1a)',''.join(document.element.itertext()))
        self.assertIn(r'\clvertalc',document_rtf(document).decode('ascii'))
        self.assertNotIn(r'\clbrdr',document_rtf(document).decode('ascii'))

    def test_actual_matrix_preserved(self):
        document=self.convert('matrix')
        self.assertEqual(len(document.element.xpath('.//m:m/m:mr')),2)
        self.assertEqual(len(document.element.xpath('.//m:m/m:mr/m:e')),4)
        self.assertEqual(len(document.element.xpath('.//m:eqArr')),0)
        self.assertIn(r'\mcount 2',document_rtf(document).decode('ascii'))

    def convert(self,name):
        case=next(c for c in CASES if c['name']==name)
        stream=io.BytesIO();make_document(case['html'],stream);stream.seek(0)
        return Document(stream)

if __name__=='__main__':unittest.main()
