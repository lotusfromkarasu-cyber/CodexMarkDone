"""Native Word/WPS clipboard, with paper styles and editable OMML equations."""
from concurrent.futures import ThreadPoolExecutor
import io
from copy import deepcopy
import unicodedata

from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn
from lxml import etree, html
import mathml2omml

MATH_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/math'
_MATHML_NS = 'http://www.w3.org/1998/Math/MathML'
_MATHML_ARITY = {
    'mfrac': 2,
    'mroot': 2,
    'msub': (2, 3),
    'msup': (2, 3),
    'msubsup': (3, 4),
    'munder': (2, 3),
    'mover': (2, 3),
    'munderover': (3, 4),
}


class _MathMLOperatorView:
    def __init__(self, element):
        self.attrs = element.attrib
        self._text = ''.join(element.itertext())

    def text(self):
        return self._text


def _group_excess_mathml_children(source):
    """Group extra operands before OMML conversion while preserving script arity."""
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    root = etree.fromstring(source.encode('utf-8'), parser)
    changed = False
    for node in root.iter():
        if not isinstance(node.tag, str):
            continue
        tag = etree.QName(node).localname.lower()
        arities = _MATHML_ARITY.get(tag)
        if arities is None:
            continue
        children = [
            child for child in node
            if isinstance(child.tag, str)
            and etree.QName(child).localname.lower() not in ('annotation', 'annotation-xml')
        ]
        max_arity = arities[0] if isinstance(arities, tuple) else arities
        if isinstance(arities, tuple):
            first = children[0] if children else None
            if first is not None and etree.QName(first).localname.lower() == 'mo':
                op = mathml2omml.op_attrs(_MathMLOperatorView(first))
                if op['largeop'] and op['form'] == 'prefix':
                    max_arity = arities[1]
        if len(children) <= max_arity:
            continue

        extras = children[max_arity - 1:]
        current_children = list(node)
        insert_at = sum(child not in extras for child in current_children[:current_children.index(extras[0])])
        namespace = etree.QName(node).namespace or _MATHML_NS
        grouped = etree.Element(f'{{{namespace}}}mrow')
        for child in extras:
            node.remove(child)
        node.insert(insert_at, grouped)
        for child in extras:
            grouped.append(child)
        changed = True

    if not changed:
        return source
    return etree.tostring(root, encoding='unicode')


def _hide_square_root_degree_placeholder(omml):
    """Mark radicals without an index as square roots in Office Math."""
    wrapper = etree.fromstring(
        ('<root xmlns:m="' + MATH_NS + '">' + omml + '</root>').encode('utf-8')
    )
    namespaces = {'m': MATH_NS}
    for radical in wrapper.xpath('.//m:rad[not(m:deg)]', namespaces=namespaces):
        properties = radical.find(qn('m:radPr'))
        if properties is None:
            properties = OxmlElement('m:radPr')
            radical.insert(0, properties)
        degree_hidden = properties.find(qn('m:degHide'))
        if degree_hidden is None:
            degree_hidden = OxmlElement('m:degHide')
            properties.append(degree_hidden)
        degree_hidden.set(qn('m:val'), '1')
        if radical.find(qn('m:deg')) is None:
            degree = OxmlElement('m:deg')
            radical.insert(radical.index(properties) + 1, degree)
    return ''.join(etree.tostring(child, encoding='unicode') for child in wrapper)


def _convert_mathml(source, layout=False):
    """Separate KaTeX display layout from mathematical matrices before OMML."""
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    root = etree.fromstring(source.encode('utf8'), parser)
    def name(node): return etree.QName(node).localname
    def children(node):
        return [c for c in node if isinstance(c.tag, str) and name(c) not in ('annotation', 'annotation-xml')]
    semantic = next((c for c in root if name(c) == 'semantics'), root)
    body = children(semantic)
    number = ''
    # KaTeX \tag: 50% spacer | formula | 50% spacer | number.
    if len(body) == 1 and name(body[0]) == 'mtable' and body[0].get('width') == '100%':
        rows = children(body[0])
        cells = children(rows[0]) if len(rows) == 1 else []
        if len(cells) == 4 and all(cells[i].get('width') == '50%' and not children(cells[i]) and not (cells[i].text or '').strip() for i in (0,2)):
            number = ''.join(cells[3].itertext())
            body = children(cells[1])
    def convert(nodes, normalize=False):
        math = etree.Element('{'+_MATHML_NS+'}math', nsmap={None:_MATHML_NS})
        row = etree.SubElement(math, '{'+_MATHML_NS+'}mrow')
        for node in nodes: row.append(deepcopy(node))
        value = etree.tostring(math, encoding='unicode')
        if normalize: return _convert_mathml(value)
        try:
            return mathml2omml.convert(value)
        except RuntimeError as exc:
            if 'Too large number of children for ' not in str(exc): raise
            return mathml2omml.convert(_group_excess_mathml_children(value))
    # Aligned/alignedat arrays have alternating right/left columns, unlike
    # actual matrices (center columns). Combine alignment cells into each row.
    while len(body) == 1 and name(body[0]) == 'mrow': body = children(body[0])
    if len(body) == 1 and name(body[0]) == 'mtable' and body[0].get('columnalign','').split()[:2] == ['right','left']:
        if layout:
            rows=[]
            for row in children(body[0]):
                rows.append([convert(children(cell), normalize=True) if ''.join(cell.itertext()).strip() else '' for cell in children(row)])
            return {'rows':rows,'number':number}
        outer = etree.Element(qn('m:oMath'))
        # Explicit right/left math columns preserve KaTeX's relation alignment
        # across Office RTF importers (which differ in eqArr alignment markers).
        array = etree.SubElement(outer, qn('m:m'))
        props = etree.SubElement(array, qn('m:mPr'))
        groups = etree.SubElement(props, qn('m:mcs'))
        alignments = body[0].get('columnalign').split()
        col = etree.SubElement(groups, qn('m:mc'))
        col_props = etree.SubElement(col, qn('m:mcPr'))
        etree.SubElement(col_props, qn('m:count')).set(qn('m:val'),str(len(alignments)))
        etree.SubElement(col_props, qn('m:mcJc')).set(qn('m:val'),'left')
        for row in children(body[0]):
            matrix_row = etree.SubElement(array, qn('m:mr'))
            for cell in children(row):
                nodes = children(cell)
                entry = etree.SubElement(matrix_row, qn('m:e'))
                if not ''.join(cell.itertext()).strip():
                    run = etree.SubElement(entry, qn('m:r'))
                    etree.SubElement(run, qn('m:t')).text = '\u2007'
                    continue
                converted = etree.fromstring(('<root xmlns:m="'+MATH_NS+'" xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'+convert(nodes)+'</root>').encode())
                for equation in converted:
                    for child in list(equation): entry.append(child)
        if number:
            entry = array[-1][-1]
            run = etree.SubElement(entry, qn('m:r'))
            etree.SubElement(run, qn('m:t')).text = '\u2003' + number
        omml = etree.tostring(outer, encoding='unicode')
    else:
        if layout: return None
        omml = convert(body)
        if number:
            wrapper = etree.fromstring(('<root xmlns:m="'+MATH_NS+'" xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'+omml+'</root>').encode())
            run = etree.SubElement(wrapper[-1], qn('m:r'))
            etree.SubElement(run, qn('m:t')).text = '\u2003' + number
            omml = ''.join(etree.tostring(c, encoding='unicode') for c in wrapper)
    wrapper = etree.fromstring(('<root xmlns:m="'+MATH_NS+'" xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'+omml+'</root>').encode())
    # Empty KaTeX mrow alignment/spacing groups become empty OMML boxes.
    # They are layout artifacts, unlike a missing operand of a fraction.
    for box in reversed(wrapper.xpath('.//m:box', namespaces={'m':MATH_NS})):
        content = box.find(qn('m:e'))
        if content is not None and not len(content) and not (content.text or '').strip() and box.find(qn('m:boxPr')) is None:
            box.getparent().remove(box)
    # User preference: every equation uses regular-weight mathematical italic,
    # independent of source \mathbf/\mathrm or the destination paragraph style.
    for run in wrapper.xpath('.//m:r', namespaces={'m':MATH_NS}):
        properties=run.find(qn('m:rPr'))
        if properties is None:properties=OxmlElement('m:rPr');run.insert(0,properties)
        for old in list(properties):
            if old.tag in (qn('m:sty'),qn('m:nor')):properties.remove(old)
        etree.SubElement(properties,qn('m:sty')).set(qn('m:val'),'i')
        for text in run.findall(qn('m:t')):
            text.text=''.join(unicodedata.normalize('NFKC',char) if 'MATHEMATICAL' in unicodedata.name(char,'') and 'BOLD' in unicodedata.name(char,'') else char for char in (text.text or ''))
    for matrix in wrapper.xpath('.//m:m', namespaces={'m':MATH_NS}):
        columns = max((len(row.findall(qn('m:e'))) for row in matrix.findall(qn('m:mr'))), default=0)
        props = matrix.find(qn('m:mPr'))
        if props is None:
            props=OxmlElement('m:mPr');matrix.insert(0,props)
        if columns and props.find(qn('m:mcs')) is None:
            group=etree.SubElement(props,qn('m:mcs'))
            column=etree.SubElement(group,qn('m:mc'))
            column_props=etree.SubElement(column,qn('m:mcPr'))
            etree.SubElement(column_props,qn('m:count')).set(qn('m:val'),str(columns))
            etree.SubElement(column_props,qn('m:mcJc')).set(qn('m:val'),'center')
    for nary in wrapper.xpath('.//m:nary', namespaces={'m':MATH_NS}):
        properties = nary.find(qn('m:naryPr'))
        if properties is None:
            properties = OxmlElement('m:naryPr'); nary.insert(0,properties)
        for arg in ('sub','sup'):
            limit = nary.find(qn('m:'+arg))
            if limit is None or not ''.join(limit.itertext()).strip():
                flag = properties.find(qn('m:'+arg+'Hide'))
                if flag is None: flag=OxmlElement('m:'+arg+'Hide');properties.append(flag)
                flag.set(qn('m:val'),'1')
    omml = ''.join(etree.tostring(c, encoding='unicode') for c in wrapper)
    return _hide_square_root_degree_placeholder(omml)


def make_document(fragment, path):
    root = html.fragment_fromstring(fragment, create_parent='div')
    doc = Document()
    normal = doc.styles['Normal']
    normal.font.name = 'Times New Roman'
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = RGBColor(0, 0, 0)
    normal.element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'), 'SimSun')
    pf = normal.paragraph_format
    pf.line_spacing = 1.4
    pf.first_line_indent = Pt(21)
    pf.space_after = Pt(8)

    def inline(parent, paragraph, bold=False, italic=False):
        def text(value):
            if value:
                r = paragraph.add_run(value)
                r.bold, r.italic = bold, italic
        text(parent.text)
        for child in parent:
            tag = etree.QName(child).localname.lower()
            if tag == 'math':
                source = etree.tostring(child, encoding='unicode', with_tail=False)
                omml = _convert_mathml(source)
                # The converter returns an XML fragment without namespace declarations.
                wrapper = etree.fromstring(('<root xmlns:m="' + MATH_NS +
                    '" xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">' + omml + '</root>').encode())
                for equation in wrapper:
                    paragraph._p.append(equation)
            elif tag == 'br':
                paragraph.add_run().add_break()
            elif tag not in ('script', 'style', 'button'):
                inline(child, paragraph, bold or tag in ('b', 'strong'), italic or tag in ('i', 'em'))
            text(child.tail)

    blocks = {'p', 'div', 'ul', 'ol', 'li', 'blockquote', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'pre', 'table'}
    heading_levels = {f'h{level}': level - 1 for level in range(1, 7)}

    def emit(node, container=doc):
        tag = etree.QName(node).localname.lower()
        if tag in ('script', 'style', 'button', 'hr'):
            return
        maths = ([node] if tag == 'math' else node.xpath('.//math'))
        if len(maths) == 1 and maths[0].get('display') == 'block' and ''.join(node.itertext()).strip() == ''.join(maths[0].itertext()).strip():
            source=etree.tostring(maths[0],encoding='unicode',with_tail=False)
            layout=_convert_mathml(source,layout=True)
            if layout:
                columns=max(len(row) for row in layout['rows'])
                table=container.add_table(rows=0,cols=columns+1)
                table.autofit=False
                borders=OxmlElement('w:tblBorders')
                for edge in ('top','left','bottom','right','insideH','insideV'):
                    edge_node=OxmlElement('w:'+edge);edge_node.set(qn('w:val'),'nil');borders.append(edge_node)
                table._tbl.tblPr.append(borders)
                total=doc.sections[0].page_width-doc.sections[0].left_margin-doc.sections[0].right_margin
                widths=[Pt(42)]*(columns-1)+[total-Pt(42)*columns,Pt(42)]
                for col,width in zip(table.columns,widths):col.width=width
                for index,row in enumerate(layout['rows']):
                    cells=table.add_row().cells
                    for cell,width in zip(cells,widths):
                        cell.width=width;cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
                    for column,value in enumerate(row):
                        p=cells[column].paragraphs[0]
                        p.alignment=WD_ALIGN_PARAGRAPH.RIGHT if column%2==0 else WD_ALIGN_PARAGRAPH.LEFT
                        p.paragraph_format.first_line_indent=Pt(0)
                        if value:
                            # Keep the cell's equation inline: Office otherwise
                            # auto-centers a math-only paragraph independently
                            # of the paragraph/cell alignment.
                            p.add_run('\u200b')
                            wrapper=etree.fromstring(('<root xmlns:m="'+MATH_NS+'" xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'+_hide_square_root_degree_placeholder(value)+'</root>').encode())
                            for equation in wrapper:p._p.append(equation)
                    cells[-1].paragraphs[0].paragraph_format.first_line_indent=Pt(0)
                    cells[-1].paragraphs[0].alignment=WD_ALIGN_PARAGRAPH.RIGHT
                    if index==len(layout['rows'])-1:cells[-1].paragraphs[0].add_run(layout['number'])
                return
        if tag == 'table':
            rows = node.xpath('./tr|./thead/tr|./tbody/tr|./tfoot/tr')
            if not rows:
                return
            cols = max(len(r.xpath('./td|./th')) for r in rows)
            table = container.add_table(rows=0, cols=cols)
            table.style = 'Table Grid'
            for row in rows:
                cells = table.add_row().cells
                for i, cell in enumerate(row.xpath('./td|./th')):
                    inline(cell, cells[i].paragraphs[0], bold=cell.tag == 'th')
                    cells[i].paragraphs[0].paragraph_format.first_line_indent = Pt(0)
            return
        if any(etree.QName(c).localname.lower() in blocks for c in node):
            if node.text and node.text.strip():
                container.add_paragraph(node.text)
            for child in node:
                emit(child, container)
                if child.tail and child.tail.strip():
                    container.add_paragraph(child.tail)
            return
        if not ''.join(node.itertext()).strip():
            return
        p = container.add_paragraph()
        # Lists intentionally become ordinary paragraphs: no Markdown bullet or dash.
        inline(node, p)
        if tag.startswith('h') and tag[1:].isdigit():
            p.paragraph_format.first_line_indent = Pt(0)
            p.paragraph_format.space_before = Pt(24 if tag == 'h1' else 10)
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.keep_with_next = True
            for run in p.runs:
                run.font.size = Pt(14 if tag == 'h1' else 13 if tag == 'h2' else 10.5)
                run.bold = True
        maths = node.xpath('.//math')
        if maths and all(m.get('display') == 'block' for m in maths):
            outside = ''.join(node.itertext())
            mathtext = ''.join(''.join(m.itertext()) for m in maths)
            if outside.strip() == mathtext.strip():
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p.paragraph_format.first_line_indent = Pt(0)
                p.paragraph_format.space_before = Pt(8)
        if tag == 'pre':
            p.paragraph_format.first_line_indent = Pt(0)
        if tag in heading_levels:
            outline_level = OxmlElement('w:outlineLvl')
            outline_level.set(qn('w:val'), str(heading_levels[tag]))
            p._p.get_or_add_pPr().append(outline_level)

    emit(root)
    # Direct formatting survives pasting into a document with a different Normal style.
    paragraphs = list(doc.paragraphs)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                paragraphs.extend(cell.paragraphs)
    for paragraph in paragraphs:
        fmt = paragraph.paragraph_format
        fmt.line_spacing = 1.4
        if fmt.first_line_indent is None:
            fmt.first_line_indent = Pt(21)
        if fmt.space_after is None:
            fmt.space_after = Pt(8)
        for run in paragraph.runs:
            run.font.name = 'Times New Roman'
            run._r.get_or_add_rPr().rFonts.set(qn('w:eastAsia'), 'SimSun')
            run.font.color.rgb = RGBColor(0, 0, 0)
            if run.font.size is None:
                run.font.size = Pt(10.5)
    old = doc.settings.element.find(qn('m:mathPr'))
    if old is not None:
        doc.settings.element.remove(old)
    doc.settings.element.append(parse_xml('<m:mathPr xmlns:m="' + MATH_NS + '"><m:mathFont m:val="Cambria Math"/></m:mathPr>'))
    doc.save(path)


_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='office-clipboard')


def _copy(fragment, target):
    if target not in ('word', 'wps'):
        raise ValueError('未知 Office 复制目标')
    from codex_markdone import set_windows_clipboard
    from office_rtf import document_rtf
    stream = io.BytesIO()
    make_document(fragment, stream)
    stream.seek(0)
    document = Document(stream)
    rtf = document_rtf(document)
    plain = html.fragment_fromstring(fragment, create_parent='div').text_content()
    set_windows_clipboard(plain, rtf=rtf)
    return True


def copy_native(fragment, target='word'):
    return _executor.submit(_copy, fragment, target).result(timeout=45)
