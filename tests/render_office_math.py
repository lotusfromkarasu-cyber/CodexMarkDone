"""Render RTF with an invisible RichEdit control; never control Office apps."""
import ctypes as c
import io
from pathlib import Path
import sys
import win32ui
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from docx import Document
from office_copy import make_document
from office_rtf import document_rtf
from test_katex_office_math import CASES
from test_office_rtf_engine import DLL

def render(destination):
    c.windll.ole32.OleInitialize(None)
    dll=c.WinDLL(str(DLL));user=c.windll.user32
    user.CreateWindowExW.argtypes=[c.c_ulong,c.c_wchar_p,c.c_wchar_p,c.c_ulong,c.c_int,c.c_int,c.c_int,c.c_int,c.c_void_p,c.c_void_p,c.c_void_p,c.c_void_p]
    user.CreateWindowExW.restype=c.c_void_p
    user.SendMessageW.argtypes=[c.c_void_p,c.c_uint,c.c_size_t,c.c_void_p];user.SendMessageW.restype=c.c_ssize_t
    user.DestroyWindow.argtypes=[c.c_void_p]
    hwnd=user.CreateWindowExW(0,'RichEdit20W','',4,0,0,1,1,c.c_void_p(-3),None,None,None)
    callback=c.WINFUNCTYPE(c.c_ulong,c.c_size_t,c.c_void_p,c.c_long,c.POINTER(c.c_long))
    class Stream(c.Structure):
        _pack_=4
        _fields_=[('cookie',c.c_size_t),('error',c.c_ulong),('callback',callback)]
    class Rect(c.Structure): _fields_=[(x,c.c_long) for x in ('left','top','right','bottom')]
    class Range(c.Structure): _fields_=[('min',c.c_long),('max',c.c_long)]
    class Format(c.Structure): _fields_=[('dc',c.c_void_p),('target',c.c_void_p),('rect',Rect),('page',Rect),('chars',Range)]
    fragment=''.join('<p>'+case['html']+'</p>' for case in CASES)
    stream=io.BytesIO();make_document(fragment,stream);stream.seek(0)
    source=io.BytesIO(document_rtf(Document(stream))); output=bytearray()
    @callback
    def read(cookie,buf,size,count):
        data=source.read(size);c.memmove(buf,data,len(data));count[0]=len(data);return 0
    @callback
    def write(cookie,buf,size,count):output.extend(c.string_at(buf,size));count[0]=size;return 0
    gdi=c.windll.gdi32;gdi.CreateDCW.argtypes=[c.c_wchar_p,c.c_wchar_p,c.c_wchar_p,c.c_void_p];gdi.CreateDCW.restype=c.c_void_p
    display=win32ui.CreateDCFromHandle(gdi.CreateDCW('DISPLAY',None,None,None))
    dc=display.CreateCompatibleDC();bitmap=win32ui.CreateBitmap();bitmap.CreateCompatibleBitmap(display,1800,1000);dc.SelectObject(bitmap);dc.FillSolidRect((0,0,1800,1000),0xffffff)
    try:
        incoming=Stream(0,0,read);user.SendMessageW(hwnd,0x449,2,c.byref(incoming));assert not incoming.error
        outgoing=Stream(0,0,write);user.SendMessageW(hwnd,0x44a,2,c.byref(outgoing));assert not outgoing.error
        dpi=dc.GetDeviceCaps(88);factor=1440/dpi
        form=Format(dc.GetSafeHdc(),dc.GetSafeHdc(),Rect(*(int(v*factor) for v in (40,40,1760,960))),Rect(0,0,int(1800*factor),int(1000*factor)),Range(0,-1))
        user.SendMessageW(hwnd,0x439,1,c.byref(form))
        Image.frombuffer('RGB',(1800,1000),bitmap.GetBitmapBits(True),'raw','BGRX',0,1).save(destination)
        print('native engine output:',len(output),'bytes; eqArr',output.count(b'\\meqArr'),'supHide',output.count(b'\\msupHide on'))
    finally:
        user.SendMessageW(hwnd,0x439,0,None);user.DestroyWindow(hwnd);dc.DeleteDC();display.DeleteDC();c.windll.ole32.OleUninitialize()

if __name__=='__main__':render(sys.argv[1])
