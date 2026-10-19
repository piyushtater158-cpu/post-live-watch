import { useMemo, useState, type ReactNode } from "react";

export interface Column<T> {
  label: string;
  sortValue: (row: T) => string | number;
  cell: (row: T) => ReactNode;
  className?: string;
}

type Dir = "ascending" | "descending";

const SortIcon = () => (
  <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
    <path d="M5 9 2 5h6z" fill="currentColor" />
  </svg>
);

/** Rows render in server order until a header is clicked; the initially marked
 *  column only shows the indicator, matching the server's pre-sorted output. */
export function SortableTable<T>({
  columns,
  rows,
  rowKey,
  initialSort,
  empty,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string | number;
  initialSort?: number;
  empty?: ReactNode;
}) {
  const [sort, setSort] = useState<{ idx: number | null; dir: Dir; applied: boolean }>({
    idx: initialSort ?? null,
    dir: "descending",
    applied: false,
  });

  const sorted = useMemo(() => {
    if (!sort.applied || sort.idx === null) return rows;
    const col = columns[sort.idx];
    const sign = sort.dir === "ascending" ? 1 : -1;
    return [...rows].sort((a, b) => {
      let x = col.sortValue(a);
      let y = col.sortValue(b);
      if (typeof x === "string") x = x.toLowerCase();
      if (typeof y === "string") y = y.toLowerCase();
      if (typeof x !== typeof y) {
        x = String(x);
        y = String(y);
      }
      return x < y ? -sign : x > y ? sign : 0;
    });
  }, [rows, columns, sort]);

  const onSort = (idx: number) =>
    setSort((s) => ({
      idx,
      dir: s.idx === idx && s.dir === "descending" ? "ascending" : "descending",
      applied: true,
    }));

  return (
    <table>
      <thead>
        <tr>
          {columns.map((c, i) => (
            <th key={c.label} scope="col" aria-sort={sort.idx === i ? sort.dir : undefined}>
              <button className="sort" type="button" onClick={() => onSort(i)}>
                {c.label}
                <SortIcon />
              </button>
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {sorted.length === 0 && empty}
        {sorted.map((r) => (
          <tr key={rowKey(r)}>
            {columns.map((c) => (
              <td key={c.label} className={c.className}>
                {c.cell(r)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
