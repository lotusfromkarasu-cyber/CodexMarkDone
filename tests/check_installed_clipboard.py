"""Explicit installed-app smoke test; replaces clipboard with a sample selection.

Does not connect to Word/WPS, activate windows or open documents.
"""
import ctypes
import json
from pathlib import Path
import subprocess
import time
import urllib.request
import urllib.error
import win32clipboard

def main():
    instance=json.loads((Path.home()/'AppData/Local/CodexMarkDone/instance.json').read_text())
    url=instance['url']
    def get(route):
        with urllib.request.urlopen(url+route,timeout=10) as response:return json.load(response)
    def process_ids():
        return sorted(subprocess.check_output(['powershell','-NoProfile','-Command',
            'Get-Process WINWORD,wps -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id'],text=True).split())
    assert get('api/health')['version']=='0.2.2'
    token=get('api/settings')['token']; before=process_ids()
    user=ctypes.windll.user32;user.GetForegroundWindow.restype=ctypes.c_void_p
    fragment='<h2>后台复制测试</h2><p>公式 <math xmlns="http://www.w3.org/1998/Math/MathML"><mfrac><mi>x</mi><msqrt><mi>y</mi></msqrt></mfrac></math></p><table><tr><td>参数</td><td>值</td></tr></table>'
    cases=json.loads((Path(__file__).parent/'fixtures/office_math_cases.json').read_text(encoding='utf8'))
    fragment+=''.join('<p>'+case['html']+'</p>' for case in cases)
    focus_changes=0;latencies=[]
    for index in range(12):
        focus=user.GetForegroundWindow();start=time.perf_counter()
        request=urllib.request.Request(url+'api/clipboard',data=json.dumps({'mode':'word' if index%2==0 else 'wps','html':fragment}).encode(),
            headers={'Origin':url.rstrip('/'),'X-Reader-Token':token,'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(request,timeout=15) as response:assert json.load(response)['ok']
        except urllib.error.HTTPError as exc:
            raise RuntimeError(exc.read().decode('utf8')) from exc
        latencies.append(time.perf_counter()-start)
        focus_changes+=user.GetForegroundWindow()!=focus
    for attempt in range(20):
        try:win32clipboard.OpenClipboard();break
        except Exception:
            if attempt==19:raise
            time.sleep(.025)
    try:
        payload=win32clipboard.GetClipboardData(win32clipboard.RegisterClipboardFormat('Rich Text Format'))
        payload=payload.decode('ascii') if isinstance(payload,bytes) else payload
        assert all(t in payload for t in (r'\mmath',r'\mrad',r'\trowd'))
    finally:win32clipboard.CloseClipboard()
    assert before==process_ids(),'Office processes changed during test'
    assert focus_changes==0,'Foreground changed during test; check for unrelated user actions'
    print(json.dumps({'copies':12,'foreground_changes':focus_changes,'office_process_ids_unchanged':True,
        'native_math_and_tables_in_clipboard':True,'max_seconds':round(max(latencies),3)}))

if __name__=='__main__':main()
