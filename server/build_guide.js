const fs = require('fs');
const C = require('./guide.js');
const { Document, Packer, Paragraph, TextRun, HeadingLevel, Table, TableRow, TableCell, WidthType, ShadingType,
  BorderStyle, AlignmentType, LevelFormat, Footer, PageNumber, TableOfContents } = require('docx');

const FONT = 'Calibri', ACC = '2A78D6', INK = '222222', MUTED = '666666';
const runs = (s, base = {}) => s.split(/(\*\*.+?\*\*)/).filter(Boolean).map(p =>
  p.startsWith('**') ? new TextRun({ ...base, text: p.slice(2, -2), bold: true }) : new TextRun({ ...base, text: p }));
const W = 9638; // ширина текста A4 при полях 2 см (DXA)
let numRef = 0;
const numbering = [{ reference: 'bul', levels: [{ level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT,
  style: { paragraph: { indent: { left: 400, hanging: 260 } } } }] }];

function table(b, width) {
  const n = b.head.length;
  const first = b.head[0] === '' ? 0.24 : (n >= 5 ? 0.24 : 0.34);
  const rest = (1 - first) / (n - 1);
  const cw = b.head.map((_, i) => Math.round(width * (i === 0 ? first : rest)));
  cw[n - 1] += width - cw.reduce((a, c) => a + c, 0);
  const border = { style: BorderStyle.SINGLE, size: 4, color: 'D0CFC8' };
  const borders = { top: border, bottom: border, left: border, right: border };
  const cell = (txt, i, head, last, keep) => new TableCell({
    width: { size: cw[i], type: WidthType.DXA }, borders,
    shading: head ? { type: ShadingType.CLEAR, color: 'auto', fill: 'E5EFFB' } : (last ? { type: ShadingType.CLEAR, color: 'auto', fill: 'F4F4F1' } : undefined),
    margins: { top: 50, bottom: 50, left: 90, right: 90 },
    children: [new Paragraph({ keepNext: keep, keepLines: true, spacing: { before: 0, after: 0 }, children: runs(txt, { size: 19, bold: head || undefined }) })] });
  const isTotal = r => /^Итого/.test(r[0]);
  return new Table({ width: { size: width, type: WidthType.DXA }, columnWidths: cw, rows: [
    new TableRow({ tableHeader: true, cantSplit: true, children: b.head.map((h, i) => cell(h, i, true, false, true)) }),
    ...b.rows.map((r, k) => new TableRow({ cantSplit: true, children: r.map((c, i) => cell(c, i, false, isTotal(r), k < b.rows.length - 1)) }))] });
}

function blocks(list, inEx = false) {
  const out = [];
  for (const b of list) {
    const indent = inEx ? { left: 240 } : undefined;
    if (b.t === 'h2') out.push(new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun(b.x)] }));
    else if (b.t === 'h3') out.push(new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(b.x)] }));
    else if (b.t === 'p') out.push(new Paragraph({ indent, keepNext: inEx || undefined, children: runs(b.x) }));
    else if (b.t === 'ul') b.items.forEach(i => out.push(new Paragraph({ numbering: { reference: 'bul', level: 0 }, children: runs(i) })));
    else if (b.t === 'ol') {
      const ref = 'num' + (numRef++);
      numbering.push({ reference: ref, levels: [{ level: 0, format: LevelFormat.DECIMAL, text: '%1.', alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 400, hanging: 300 } } } }] });
      b.items.forEach(i => out.push(new Paragraph({ numbering: { reference: ref, level: 0 }, children: runs(i) })));
    }
    else if (b.t === 'code') b.x.split('\n').forEach((ln, k, arr) => out.push(new Paragraph({ indent: { left: 240 },
      spacing: { before: k ? 0 : 60, after: k === arr.length - 1 ? 120 : 0 }, keepNext: k < arr.length - 1,
      shading: { type: ShadingType.CLEAR, color: 'auto', fill: 'F0EFEC' },
      children: [new TextRun({ text: ln || ' ', font: 'Consolas', size: 20 })] })));
    else if (b.t === 'table') { out.push(table(b, inEx ? W - 240 : W)); out.push(new Paragraph({ spacing: { after: 60 }, children: [] })); }
    else if (b.t === 'ex') {
      out.push(new Paragraph({ keepNext: true, spacing: { before: 200, after: 80 },
        border: { left: { style: BorderStyle.SINGLE, size: 18, color: ACC, space: 8 } }, indent: { left: 120 },
        children: [new TextRun({ text: b.title, bold: true, color: ACC })] }));
      out.push(...blocks(b.body, true));
    }
  }
  return out;
}

const body = blocks(C);
const doc = new Document({
  creator: 'MP Control', title: 'Перенос MP Control на сервер',
  styles: {
    default: { document: { run: { font: FONT, size: 22, color: INK }, paragraph: { spacing: { after: 100, line: 276 } } } },
    paragraphStyles: [
      { id: 'Title', name: 'Title', basedOn: 'Normal', run: { size: 40, bold: true, color: INK }, paragraph: { spacing: { after: 80 } } },
      { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: 30, bold: true, color: INK }, paragraph: { spacing: { before: 360, after: 120 }, keepNext: true, outlineLevel: 0 } },
      { id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: 24, bold: true, color: INK }, paragraph: { spacing: { before: 220, after: 80 }, keepNext: true, outlineLevel: 1 } },
    ]
  },
  numbering: { config: numbering },
  sections: [{
    properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1134, bottom: 1134, left: 1134, right: 1134 } } },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.RIGHT,
      children: [new TextRun({ text: 'MP Control — перенос на сервер · стр. ', size: 16, color: MUTED }),
        new TextRun({ children: [PageNumber.CURRENT], size: 16, color: MUTED })] })] }) },
    children: [
      new Paragraph({ heading: HeadingLevel.TITLE, children: [new TextRun('Перенос MP Control на сервер')] }),
      new Paragraph({ spacing: { after: 240 }, border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: ACC, space: 6 } },
        children: [new TextRun({ text: 'Установка, перенос базы, обновления через GitHub · редакция от ' + new Date().toLocaleDateString('ru-RU'), color: MUTED, size: 20 })] }),
      new Paragraph({ spacing: { after: 60 }, children: [new TextRun({ text: 'Содержание', bold: true })] }),
      ...C.filter(b => b.t === 'h2').map(b => new Paragraph({ spacing: { after: 20 }, indent: { left: 240 }, children: [new TextRun({ text: b.x, color: INK })] })),
      new Paragraph({ spacing: { after: 120 }, children: [] }),
      ...body
    ]
  }]
});
Packer.toBuffer(doc).then(b => { fs.writeFileSync(process.argv[2], b); console.log('docx ok', b.length); });
