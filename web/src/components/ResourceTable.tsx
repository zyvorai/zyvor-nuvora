import { useState, type ReactNode } from 'react';
import { Layers3 } from 'lucide-react';
import { time, type Row } from '../api';
import { Badge, ListEmpty, TableWrap, Toolbar } from './kit';

function format(r: Row, k: string): ReactNode {
  const v = r[k];
  if (k === 'status') return <Badge value={v} />;
  if (k === 'created') return time(v);
  if (Array.isArray(v)) return typeof v[0] === 'object' ? `${v.length} items` : v.join(', ');
  if (typeof v === 'boolean') return v ? 'Enabled' : 'Disabled';
  return String(v ?? '—');
}

export default function ResourceTable({
  rows,
  columns,
  onRow,
  renderAction,
  emptyTitle = 'Nothing here yet',
  emptyText = 'Create your first resource to get started.',
}: {
  rows: Row[];
  columns: string[];
  onRow?: (r: Row) => void;
  renderAction?: (r: Row) => ReactNode;
  emptyTitle?: string;
  emptyText?: string;
}) {
  const [search, setSearch] = useState('');
  const q = search.toLowerCase();
  const visible = q ? rows.filter((r) => JSON.stringify(r).toLowerCase().includes(q)) : rows;
  return (
    <div className="browse">
      <Toolbar
        search={search}
        onSearchChange={setSearch}
        placeholder="Search…"
        searchLabel="Search resources"
        trailing={<span className="toolbar-count">{visible.length} of {rows.length}</span>}
      />
      <TableWrap>
        {visible.length ? (
          <table>
            <thead>
              <tr>
                {columns.map((c) => (
                  <th key={c}>{c.replaceAll('_', ' ')}</th>
                ))}
                {renderAction && <th>Action</th>}
              </tr>
            </thead>
            <tbody>
              {visible.map((r) => (
                <tr key={r.id}>
                  {columns.map((c, i) => (
                    <td key={c}>
                      {i === 0 && onRow ? (
                        <button type="button" className="link" onClick={() => onRow(r)}>
                          {format(r, c)}
                        </button>
                      ) : (
                        format(r, c)
                      )}
                    </td>
                  ))}
                  {renderAction && <td>{renderAction(r)}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <ListEmpty icon={Layers3} title={rows.length ? 'No matches' : emptyTitle} description={rows.length ? 'Try a different search.' : emptyText} />
        )}
      </TableWrap>
    </div>
  );
}
