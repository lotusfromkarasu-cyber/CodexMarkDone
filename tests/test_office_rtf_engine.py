"""Headless RTF round trip using Office's RichEdit DLL, not Word/WPS automation."""
import ctypes as c
import io
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from docx import Document
from office_copy import make_document
from office_rtf import document_rtf

DLL=Path('C:/Program Files/Microsoft Office/root/vfs/ProgramFilesCommonX64/Microsoft Shared/OFFICE16/RICHED20.DLL')

@unittest.skipUnless(sys.platform=='win32' and DLL.exists(),'Office RichEdit DLL not installed')
class RichEditTests(unittest.TestCase):
    def test_native_parser_retains_math_and_table(self):
        c.windll.ole32.OleInitialize(None)
        engine=c.WinDLL(str(DLL)); user=c.windll.user32
        user.CreateWindowExW.argtypes=[c.c_ulong,c.c_wchar_p,c.c_wchar_p,c.c_ulong,c.c_int,c.c_int,c.c_int,c.c_int,c.c_void_p,c.c_void_p,c.c_void_p,c.c_void_p]
        user.CreateWindowExW.restype=c.c_void_p
        user.SendMessageW.argtypes=[c.c_void_p,c.c_uint,c.c_size_t,c.c_void_p]
        user.SendMessageW.restype=c.c_ssize_t
        user.DestroyWindow.argtypes=[c.c_void_p]
        hwnd=user.CreateWindowExW(0,'RichEdit20W','',4,0,0,1,1,c.c_void_p(-3),None,None,None)
        self.assertTrue(hwnd,'Unable to create message-only RichEdit')
        callback=c.WINFUNCTYPE(c.c_ulong,c.c_size_t,c.c_void_p,c.c_long,c.POINTER(c.c_long))
        class Stream(c.Structure):
            _pack_=4
            _fields_=[('cookie',c.c_size_t),('error',c.c_ulong),('callback',callback)]
        stream=io.BytesIO()
        make_document('<p><strong>Figure 5(b) 中文</strong> <math xmlns="http://www.w3.org/1998/Math/MathML"><mfrac><msup><mi>x</mi><mn>2</mn></msup><msqrt><mi>y</mi></msqrt></mfrac></math></p><table><tr><th>A</th><td>B</td></tr></table>',stream)
        stream.seek(0); source=io.BytesIO(document_rtf(Document(stream),suppress_text_bold=True)); output=bytearray()
        @callback
        def read(cookie,buf,size,count):
            data=source.read(size);c.memmove(buf,data,len(data));count[0]=len(data);return 0
        @callback
        def write(cookie,buf,size,count):
            output.extend(c.string_at(buf,size));count[0]=size;return 0
        try:
            incoming=Stream(0,0,read);user.SendMessageW(hwnd,0x449,2,c.byref(incoming));self.assertEqual(incoming.error,0)
            outgoing=Stream(0,0,write);user.SendMessageW(hwnd,0x44a,2,c.byref(outgoing));self.assertEqual(outgoing.error,0)
            rtf=output.decode('ascii')
            for token in (r'\mmath',r'\mf',r'\msSup',r'\mrad',r'\trowd'):
                self.assertIn(token,rtf)
            self.assertIn('Figure 5(b)',rtf)
            self.assertNotRegex(rtf,r'\\(?:b|ab)(?!0\b)(?:\d+)?(?=[^a-zA-Z]|$)')
        finally:
            user.DestroyWindow(hwnd)
            c.windll.ole32.OleUninitialize()

if __name__=='__main__':unittest.main()
