"""Serialize our DOCX selection to eager RTF; no Office process or COM needed.

Math destinations follow RTF 1.9.1 (OMML names with an m prefix); see the
LibreOffice math-rad.rtf interoperability fixture for the mmath envelope.
"""
from docx.oxml.ns import qn

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
M = 'http://schemas.openxmlformats.org/officeDocument/2006/math'

def escape(value):
    out = []
    for c in value or '':
        if c in '\\{}':
            out.append('\\' + c)
        elif c == '\n':
            out.append(r'\line ')
        elif c == '\t':
            out.append(r'\tab ')
        elif 32 <= ord(c) < 127:
            out.append(c)
        else:
            raw = c.encode('utf-16-le')
            for i in range(0, len(raw), 2):
                n = int.from_bytes(raw[i:i+2], 'little', signed=True)
                out.append('\\u' + str(n) + '?')
    return ''.join(out)

def math(node):
    tag = node.tag.rsplit('}', 1)[-1]
    ns = node.tag.split('}')[0].lstrip('{')
    if ns == W:
        if tag == 't': return escape(node.text)
        if tag == 'rPr': return ''
        return ''.join(math(c) for c in node)
    if ns != M: raise ValueError('不支持的公式命名空间：' + ns)
    if tag == 't': return escape(node.text)
    if tag == 'r':
        controls = r'\f2\b0\i\msty2 '
        return '{\\mr ' + controls + ''.join(math(c) for c in node if c.tag != qn('m:rPr')) + '}'
    if tag in ('rPr', 'ctrlPr'): return ''
    control = {'oMath':'moMath','oMathPara':'moMathPara','sSub':'msSub','sSup':'msSup','sSubSup':'msSubSup'}.get(tag, 'm' + tag)
    value = node.get(qn('m:val'))
    if value is not None:
        # Math property destinations use a text argument, including on/off.
        if tag in ('degHide','subHide','supHide','grow','aln','diff','noBreak','nor','opEmu','plcHide','show','transp','zeroAsc','zeroDesc','zeroWid','strikeBLTR','strikeH','strikeTLBR','strikeV'):
            if value in ('true','1'): value = 'on'
            elif value in ('false','0'): value = 'off'
        return '{\\' + control + ' ' + escape(value) + '}'
    prefix = '\\*' if tag in ('oMath','oMathPara') else ''
    return '{' + prefix + '\\' + control + ' ' + ''.join(math(c) for c in node) + '}'

def run(node):
    controls = ''
    prop = node.find(qn('w:rPr'))
    if prop is not None:
        for name, control in [('b','b'),('i','i')]:
            child = prop.find(qn('w:'+name))
            if child is not None and child.get(qn('w:val'), '1') not in ('0','false'):
                controls += '\\' + control + ' '
        size = prop.find(qn('w:sz'))
        if size is not None: controls += '\\fs' + size.get(qn('w:val')) + ' '
    content = []
    for child in node:
        if child.tag == qn('w:t'): content.append(escape(child.text))
        elif child.tag == qn('w:br'): content.append(r'\line ')
        elif child.tag == qn('w:tab'): content.append(r'\tab ')
    return '{' + controls + ''.join(content) + '}'

def paragraph(node, in_table=False, end=True):
    controls = r'\pard\plain\f0\af1\lang2052\langfe2052\fs21\cf1\highlight0\sl336\slmult1\sa160 '
    controls += r'\intbl ' if in_table else ''
    properties = node.find(qn('w:pPr'))
    if properties is not None:
        align = properties.find(qn('w:jc'))
        if align is not None:
            controls += {'center':r'\qc ','right':r'\qr ','both':r'\qj '}.get(align.get(qn('w:val')), r'\ql ')
        ind = properties.find(qn('w:ind'))
        if ind is not None:
            controls += '\\fi' + ind.get(qn('w:firstLine'), '0') + ' '
        spacing = properties.find(qn('w:spacing'))
        if spacing is not None:
            for key, rtf in [('before','sb'),('after','sa')]:
                value = spacing.get(qn('w:'+key))
                if value: controls += '\\' + rtf + value + ' '
        outline = properties.find(qn('w:outlineLvl'))
        if outline is not None: controls += '\\outlinelevel' + outline.get(qn('w:val')) + ' '
        if properties.find(qn('w:keepNext')) is not None: controls += r'\keepn '
    parts = [controls]
    for child in node:
        if child.tag == qn('w:r'): parts.append(run(child))
        elif child.tag in (qn('m:oMath'), qn('m:oMathPara')):
            parts.append('{\\mmath\\b0\\i ' + math(child) + '}')
    return ''.join(parts) + (r'\par ' if end else '')

def table(node):
    result=[]
    borders=node.find('./'+qn('w:tblPr')+'/'+qn('w:tblBorders'))
    borderless=borders is not None and all(c.get(qn('w:val')) in ('nil','none') for c in borders)
    for row in node.findall(qn('w:tr')):
        cells=row.findall(qn('w:tc'))
        result.append(r'\trowd\trgaph108\trleft0 ')
        right=0
        for cell in cells:
            width=cell.find('./'+qn('w:tcPr')+'/'+qn('w:tcW'))
            right += int(width.get(qn('w:w'))) if width is not None and width.get(qn('w:type'))=='dxa' else 9000//max(1,len(cells))
            rule='' if borderless else r'\clbrdrt\brdrs\brdrw10\clbrdrl\brdrs\brdrw10\clbrdrb\brdrs\brdrw10\clbrdrr\brdrs\brdrw10'
            valign=cell.find('./'+qn('w:tcPr')+'/'+qn('w:vAlign'))
            if valign is not None and valign.get(qn('w:val'))=='center':rule+=r'\clvertalc '
            result.append(rule+'\\cellx'+str(right)+' ')
        for cell in cells:
            paragraphs=cell.findall(qn('w:p'))
            for index, p in enumerate(paragraphs): result.append(paragraph(p,True,index<len(paragraphs)-1))
            result.append(r'\cell ')
        result.append(r'\row ')
    return ''.join(result)

def document_rtf(document):
    parts=[r'{\rtf1\ansi\ansicpg1252\deff0\uc1',
           r'{\fonttbl{\f0\froman Times New Roman;}{\f1\fnil\fcharset134 SimSun;}{\f2\froman Cambria Math;}}',
           r'{\colortbl;\red0\green0\blue0;}', r'\viewkind4 ']
    for node in document.element.body:
        if node.tag == qn('w:p'): parts.append(paragraph(node))
        elif node.tag == qn('w:tbl'): parts.append(table(node))
    parts.append('}')
    return ''.join(parts).encode('ascii')
