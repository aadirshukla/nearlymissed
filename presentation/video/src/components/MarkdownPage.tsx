import React from 'react';
import {C, F} from '../theme';

// Minimal renderer for the exported evidence brief: headings, quotes, tables,
// bullets, rules and paragraphs. Text is shown verbatim (escapes removed).
const unescape = (s: string) => s.replace(/\\([\\`*_{}[\]()#+\-.!|>])/g, '$1');

const inline = (s: string): React.ReactNode[] =>
  unescape(s)
    .split(/(\*\*[^*]+\*\*|\*[^*]+\*)/g)
    .filter(Boolean)
    .map((part, i) =>
      part.startsWith('**') ? <strong key={i}>{part.slice(2, -2)}</strong> : part.startsWith('*') ? <em key={i}>{part.slice(1, -1)}</em> : <React.Fragment key={i}>{part}</React.Fragment>,
    );

const cells = (row: string) => row.trim().replace(/^\||\|$/g, '').split(/(?<!\\)\|/).map((c) => c.trim());

export const MarkdownPage: React.FC<{text: string; width: number; scale?: number}> = ({text, width, scale = 1}) => {
  const lines = text.split('\n');
  const blocks: React.ReactNode[] = [];
  let i = 0;
  const s = (n: number) => n * scale;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i++;
      continue;
    }
    if (line.startsWith('|')) {
      const rows: string[][] = [];
      while (i < lines.length && lines[i].startsWith('|')) {
        if (!/^\|[\s|:-]+\|$/.test(lines[i].trim())) rows.push(cells(lines[i]));
        i++;
      }
      blocks.push(
        <table key={i} style={{width: '100%', borderCollapse: 'collapse', margin: `${s(8)}px 0 ${s(18)}px`, fontSize: s(17)}}>
          <tbody>
            {rows.map((r, ri) => (
              <tr key={ri} style={{borderBottom: `1px solid #D8D2C6`, background: ri === 0 ? '#E9E4D9' : undefined}}>
                {r.map((c, ci) => (
                  <td key={ci} style={{padding: `${s(6)}px ${s(10)}px`, fontWeight: ri === 0 ? 600 : 400, verticalAlign: 'top'}}>{inline(c)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>,
      );
      continue;
    }
    if (line.startsWith('#')) {
      const level = line.match(/^#+/)![0].length;
      blocks.push(
        <div key={i} data-heading={line.replace(/^#+\s*/, '')} style={{fontFamily: level === 1 ? F.serif : F.sans, fontStyle: level === 1 ? 'italic' : 'normal', fontSize: s(level === 1 ? 44 : 26), fontWeight: level === 1 ? 400 : 700, margin: `${s(level === 1 ? 0 : 22)}px 0 ${s(10)}px`, lineHeight: 1.15}}>
          {inline(line.replace(/^#+\s*/, ''))}
        </div>,
      );
    } else if (line.startsWith('>')) {
      blocks.push(
        <div key={i} style={{borderLeft: `${s(5)}px solid ${C.amber}`, background: '#FBEBD0', padding: `${s(10)}px ${s(16)}px`, margin: `${s(8)}px 0 ${s(14)}px`, fontSize: s(19)}}>
          {inline(line.replace(/^>\s*/, ''))}
        </div>,
      );
    } else if (line.startsWith('- ')) {
      blocks.push(
        <div key={i} style={{fontSize: s(18), margin: `${s(4)}px 0`, paddingLeft: s(22), textIndent: -s(16), lineHeight: 1.4}}>
          •&nbsp;&nbsp;{inline(line.slice(2))}
        </div>,
      );
    } else if (line.trim() === '---') {
      blocks.push(<div key={i} style={{borderTop: '1px solid #C9C2B4', margin: `${s(18)}px 0`}} />);
    } else {
      blocks.push(
        <div key={i} style={{fontSize: s(19), lineHeight: 1.5, margin: `${s(4)}px 0 ${s(12)}px`}}>
          {inline(line)}
        </div>,
      );
    }
    i++;
  }
  return (
    <div style={{width, background: C.paper, color: C.paperInk, fontFamily: F.sans, padding: `${s(48)}px ${s(56)}px`, boxSizing: 'border-box'}}>{blocks}</div>
  );
};
