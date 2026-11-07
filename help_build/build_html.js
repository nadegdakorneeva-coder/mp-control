const C = require('./content.js');
const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const inl = s => esc(s).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
const toc = [];
function blk(b) {
  switch (b.t) {
    case 'h2': { const id = 'h' + toc.length; toc.push([id, b.x]); return `<h2 id="${id}">${inl(b.x)}</h2>`; }
    case 'h3': return `<h3>${inl(b.x)}</h3>`;
    case 'p': return `<p>${inl(b.x)}</p>`;
    case 'ul': return `<ul>${b.items.map(i => `<li>${inl(i)}</li>`).join('')}</ul>`;
    case 'ol': return `<ol>${b.items.map(i => `<li>${inl(i)}</li>`).join('')}</ol>`;
    case 'table': return `<div class="tbl help-tbl"><table><thead><tr>${b.head.map(h => `<th class="l">${inl(h)}</th>`).join('')}</tr></thead><tbody>${b.rows.map(r => `<tr>${r.map(c => `<td class="l">${inl(c)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
    case 'ex': return `<div class="help-ex"><div class="help-ex-t">${inl(b.title)}</div>${b.body.map(blk).join('')}</div>`;
  }
}
const body = C.map(blk).join('\n');
const html = `<!-- сгенерировано из help_build/content.js -->\n<div class="help"><nav class="help-toc">${toc.map(([id, t]) => `<a href="#" data-to="${id}">${esc(t)}</a>`).join('')}</nav><div class="help-body">${body}</div></div>\n`;
require('fs').writeFileSync(process.argv[2], html);
console.log('html ok', html.length);
