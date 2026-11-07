// guide.js → README.md (для GitHub)
const C = require('./guide.js');
const out = ['# Перенос дашборда Mocheqi на сервер', ''];
const blk = (b, q = '') => {
  switch (b.t) {
    case 'h2': out.push('## ' + b.x, ''); break;
    case 'h3': out.push('### ' + b.x, ''); break;
    case 'p': out.push(q + b.x, ''); break;
    case 'ul': b.items.forEach(i => out.push(q + '- ' + i)); out.push(''); break;
    case 'ol': b.items.forEach((i, k) => out.push(q + (k + 1) + '. ' + i)); out.push(''); break;
    case 'code': out.push('```bash', b.x, '```', ''); break;
    case 'table': out.push('| ' + b.head.join(' | ') + ' |', '|' + b.head.map(() => '---').join('|') + '|',
      ...b.rows.map(r => '| ' + r.map(c => c.replace(/\|/g, '\\|')).join(' | ') + ' |'), ''); break;
    case 'ex': out.push('> **' + b.title + '**', '>'); b.body.forEach(x => blk(x, '> ')); break;
  }
};
C.forEach(b => blk(b));
require('fs').writeFileSync(process.argv[2], out.join('\n').replace(/\\\\/g, '\\'));
