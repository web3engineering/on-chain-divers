import { useState, type ReactElement } from 'react';
import { Glyph, SUBJECT_NAMES, type Subject } from './Article';

/* Figures for the article template. Diagrams marked "illustration" use
   made-up numbers; Heatmap, CrossDiagram and PipeDiagram draw real query
   results passed in by scripts/render_articles.py. */

const shortAddr = (a: string) => (a.length > 12 ? `${a.slice(0, 4)}…${a.slice(-4)}` : a);
const sol = (lamports: number) =>
  (lamports / 1e9).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 });

// ---------------------------------------------------------------------------
// Three tables, one lane each (illustration)
// ---------------------------------------------------------------------------

function Head({ x, y, deg = 0 }: { x: number; y: number; deg?: number }) {
  return <polygon className="head" points="0,0 -9,-4.5 -9,4.5" transform={`translate(${x} ${y}) rotate(${deg})`} />;
}

function Packet({ path, dur = 2.6, begin = 0 }: { path: string; dur?: number; begin?: number }) {
  return (
    <circle className="packet" r="4">
      <animateMotion path={path} dur={`${dur}s`} begin={`${begin}s`} repeatCount="indefinite" />
    </circle>
  );
}

function Node({ x, cy, label, fresh, w = 112 }: { x: number; cy: number; label: string; fresh?: boolean; w?: number }) {
  return (
    <g>
      <rect className={fresh ? 'node node--new' : 'node'} x={x} y={cy - 18} width={w} height="36" rx="18" />
      <text className="t-ink" x={x + w / 2} y={cy + 4.5} textAnchor="middle" fontSize="13">
        {label}
      </text>
    </g>
  );
}

function TopUpLane() {
  const c = 42;
  const path = `M118,${c} L274,${c}`;
  return (
    <svg className="oa-svg" viewBox="0 0 400 84" role="img" aria-label="A signer sends SOL to a wallet whose balance was zero">
      <path className="edge" d={path} strokeWidth="3" />
      <Head x={280} y={c} />
      <Packet path={path} />
      <Node x={6} cy={c} label="Signer" />
      <Node x={282} cy={c} label="Empty wallet" fresh />
      <text className="t-ink" x="200" y={c - 12} textAnchor="middle" fontSize="13">
        0 → 0.0035 SOL
      </text>
      <text x="200" y={c + 22} textAnchor="middle" fontSize="12">
        any amount
      </text>
    </svg>
  );
}

function FundingLane() {
  const c = 60;
  const up = `M118,${c - 10} C168,${c - 44} 232,${c - 44} 275,${c - 13}`;
  const mid = `M118,${c} L274,${c}`;
  const down = `M118,${c + 10} C168,${c + 44} 232,${c + 44} 275,${c + 13}`;
  return (
    <svg
      className="oa-svg"
      viewBox="0 0 400 120"
      role="img"
      aria-label="A wallet that already holds SOL receives more, several times; each change above 0.09 SOL is recorded"
    >
      <path className="edge" d={up} strokeWidth="2" />
      <path className="edge" d={mid} strokeWidth="2" />
      <path className="edge" d={down} strokeWidth="2" />
      <Head x={280} y={c - 9} deg={36} />
      <Head x={280} y={c} />
      <Head x={280} y={c + 9} deg={-36} />
      <Packet path={up} dur={2.4} begin={0} />
      <Packet path={mid} dur={2.4} begin={0.8} />
      <Packet path={down} dur={2.4} begin={1.6} />
      <Node x={6} cy={c} label="Wallet A" />
      <Node x={282} cy={c} label="Wallet B" />
      <text className="t-ink" x="200" y={c - 46} textAnchor="middle" fontSize="13">
        every change above 0.09 SOL
      </text>
      <text x="200" y={c + 55} textAnchor="middle" fontSize="12">
        balance before can be anything
      </text>
    </svg>
  );
}

function TransferLane() {
  const c = 48;
  const out = `M118,${c - 10} L274,${c - 10}`;
  const back = `M282,${c + 10} L126,${c + 10}`;
  return (
    <svg className="oa-svg" viewBox="0 0 400 96" role="img" aria-label="Two owners send tokens to each other">
      <path className="edge" d={out} strokeWidth="2" />
      <path className="edge" d={back} strokeWidth="2" />
      <Head x={280} y={c - 10} />
      <Head x={120} y={c + 10} deg={180} />
      <Packet path={out} dur={2.8} />
      <Packet path={back} dur={2.8} begin={1.4} />
      <Node x={6} cy={c} label="Owner A" />
      <Node x={282} cy={c} label="Owner B" />
      <text className="t-ink" x="200" y={c - 22} textAnchor="middle" fontSize="13">
        USDC, wSOL, any mint
      </text>
      <text x="200" y={c + 34} textAnchor="middle" fontSize="12">
        Token and Token-2022
      </text>
    </svg>
  );
}

const LANES: { subject: Subject; table: string; note: string; svg: () => ReactElement }[] = [
  { subject: 'topup', table: 'sol_top_ups', note: 'A SOL balance goes from zero to above zero.', svg: TopUpLane },
  {
    subject: 'funding',
    table: 'indexer3_sol_fundings',
    note: 'One wallet loses SOL and another gains it, whatever the balance was.',
    svg: FundingLane,
  },
  { subject: 'transfer', table: 'token_transfers', note: 'A token moves from one owner to another.', svg: TransferLane },
];

export function FlowLanes() {
  return (
    <div>
      {LANES.map(({ subject, table, note, svg: Svg }) => (
        <div className={`oa-lane oa-${subject}`} key={subject}>
          <div>
            <div className="oa-lane__name">
              <Glyph subject={subject} />
              {SUBJECT_NAMES[subject]}
            </div>
            <div className="oa-lane__table">{table}</div>
            <div className="oa-lane__note">{note}</div>
          </div>
          <Svg />
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// One wallet's SOL balance and which table records each change (illustration)
// ---------------------------------------------------------------------------

type Recorded = 'both' | 'funding' | 'none';

interface BalanceEvent {
  day: number;
  delta: number;
  rec: Recorded;
  what: string;
}

const EVENTS: BalanceEvent[] = [
  { day: 1, delta: 2.0, rec: 'both', what: 'Receives 2.00 SOL' },
  { day: 3, delta: -0.6, rec: 'none', what: 'Buys a token from a pool' },
  { day: 5, delta: 0.5, rec: 'funding', what: 'Receives 0.50 SOL' },
  { day: 7, delta: 0.05, rec: 'none', what: 'Receives 0.05 SOL' },
  { day: 9, delta: -1.95, rec: 'funding', what: 'Sends everything out' },
  { day: 12, delta: 1.0, rec: 'both', what: 'Receives 1.00 SOL' },
];

const REC_LABEL: Record<Recorded, string> = {
  both: 'Top-up row + funding row',
  funding: 'Funding row only',
  none: 'No row',
};
const REC_CLASS: Record<Recorded, string> = { both: 'oa-topup', funding: 'oa-funding', none: 'oa-none' };

const LAST_DAY = 14;
const Y_MAX = 2.3;
const Y_TICKS = [0, 0.5, 1, 1.5, 2];

const STEPS = (() => {
  let balance = 0;
  return EVENTS.map((e) => {
    const before = balance;
    balance = Math.round((balance + e.delta) * 100) / 100;
    return { ...e, before, after: balance };
  });
})();

const signed = (v: number) => `${v > 0 ? '+' : '−'}${Math.abs(v).toFixed(2)}`;

function BalancePlot({ w, h, compact }: { w: number; h: number; compact?: boolean }) {
  const [active, setActive] = useState<number | null>(null);
  const m = { l: compact ? 30 : 38, r: compact ? 10 : 18, t: 30, b: 28 };
  const x = (day: number) => m.l + (day / LAST_DAY) * (w - m.l - m.r);
  const y = (v: number) => h - m.b - (v / Y_MAX) * (h - m.t - m.b);
  const font = compact ? 11 : 12;

  let d = `M${x(0)},${y(0)}`;
  for (const s of STEPS) d += ` H${x(s.day)} V${y(s.after)}`;
  d += ` H${x(LAST_DAY)}`;
  const area = `${d} V${y(0)} H${x(0)} Z`;

  const cur = active === null ? null : STEPS[active];
  const tipLeft = cur ? Math.min(Math.max((x(cur.day) / w) * 100, compact ? 30 : 14), compact ? 70 : 86) : 0;
  const edges = [0, ...STEPS.slice(1).map((s, i) => (STEPS[i].day + s.day) / 2), LAST_DAY];

  return (
    <div className={`oa-chart ${compact ? 'oa-chart--narrow' : 'oa-chart--wide'}`} onPointerLeave={() => setActive(null)}>
      <svg
        className="oa-svg"
        viewBox={`0 0 ${w} ${h}`}
        role="img"
        aria-label="Step chart of one wallet's SOL balance over 14 days. It is topped up from zero to 2.00 SOL on day 1, receives 0.50 SOL on day 5 and 0.05 SOL on day 7, is emptied on day 9 and topped up from zero again on day 12."
      >
        {Y_TICKS.map((t) => (
          <g key={t}>
            <line className={t === 0 ? 'axis' : 'grid'} x1={m.l} x2={w - m.r} y1={y(t)} y2={y(t)} />
            <text x={m.l - 8} y={y(t) + 4} textAnchor="end" fontSize={font}>
              {t.toFixed(1)}
            </text>
          </g>
        ))}
        {Array.from({ length: LAST_DAY / 2 + 1 }, (_, i) => i * 2).map((day) => (
          <text key={day} x={x(day)} y={h - 6} textAnchor="middle" fontSize={font}>
            {day === 0 ? 'Day 0' : day}
          </text>
        ))}

        <path className="area" d={area} />
        <path className="line" d={d} />

        {cur && <line className="cursor" x1={x(cur.day)} x2={x(cur.day)} y1={m.t - 8} y2={y(0)} />}

        {STEPS.map((s, i) => (
          <g className={REC_CLASS[s.rec]} key={s.day}>
            <line className="riser" x1={x(s.day)} x2={x(s.day)} y1={y(s.before)} y2={y(s.after)} />
            <circle className="dot" cx={x(s.day)} cy={y(s.after)} r={active === i ? 6.5 : 5} />
          </g>
        ))}

        <text className="t-ink" x={x(1) + 11} y={y(2.0) - 9} fontSize={font}>
          {compact ? '0 → 2.00' : 'Top-up: 0 → 2.00'}
        </text>
        <text className="t-ink" x={x(5)} y={y(1.9) - 12} textAnchor="middle" fontSize={font}>
          +0.50
        </text>
        <text x={compact ? x(8) : x(7) + 6} y={y(1.95) + 17} textAnchor={compact ? 'middle' : 'start'} fontSize={font}>
          {compact ? '+0.05' : '+0.05, dust'}
        </text>
        <text className="t-ink" x={x(9) + 10} y={y(1.3)} fontSize={font}>
          {compact ? '−1.95 to zero' : '−1.95, wallet emptied'}
        </text>
        <text className="t-ink" x={x(LAST_DAY)} y={y(1.0) - 12} textAnchor="end" fontSize={font}>
          {compact ? 'again: 0 → 1.00' : 'Top-up again: 0 → 1.00'}
        </text>

        {STEPS.map((s, i) => (
          <rect
            className="hit"
            key={s.day}
            x={x(edges[i])}
            y={m.t - 8}
            width={x(edges[i + 1]) - x(edges[i])}
            height={y(0) - m.t + 8}
            onPointerEnter={() => setActive(i)}
            onPointerDown={() => setActive(i)}
          />
        ))}
      </svg>

      {cur && (
        <div className="oa-tip" style={{ left: `${tipLeft}%`, top: `${(y(Math.max(cur.before, cur.after)) / h) * 100}%` }}>
          <div className="oa-tip__day">Day {cur.day}</div>
          <div className="oa-tip__row">
            <span>{cur.what}</span>
            <b>{signed(cur.delta)} SOL</b>
          </div>
          <div className="oa-tip__row">
            <span>Balance</span>
            <b>
              {cur.before.toFixed(2)} → {cur.after.toFixed(2)}
            </b>
          </div>
          <div className={`oa-tip__row ${REC_CLASS[cur.rec]}`}>
            <span>
              <i className="oa-swatch" />
              {REC_LABEL[cur.rec]}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

/* Rendered at two fixed sizes so type stays legible; CSS shows one of them. */
export function BalanceTimeline() {
  return (
    <>
      <ul className="oa-legend oa-legend--block">
        {(['both', 'funding', 'none'] as Recorded[]).map((rec) => (
          <li className={REC_CLASS[rec]} key={rec}>
            <i className="oa-swatch" />
            {REC_LABEL[rec]}
          </li>
        ))}
      </ul>
      <BalancePlot w={690} h={310} />
      <BalancePlot w={358} h={270} compact />
    </>
  );
}

// ---------------------------------------------------------------------------
// Heat map of query result rows
// ---------------------------------------------------------------------------

type Row = Record<string, string | number>;

interface HeatmapProps {
  data: Row[];
  x: string;
  y: string;
  value: string;
  xOrder?: string;
  yOrder?: string;
  xLabel?: string;
  yLabel?: string;
  unit?: string;
}

function axis(data: Row[], key: string, order?: string): string[] {
  const seen = new Map<string, number>();
  data.forEach((row, i) => {
    const label = String(row[key]);
    if (!seen.has(label)) seen.set(label, order ? Number(row[order]) : i);
  });
  return [...seen.entries()].sort((a, b) => a[1] - b[1]).map(([label]) => label);
}

export function Heatmap({ data, x, y, value, xOrder, yOrder, xLabel, yLabel, unit = '' }: HeatmapProps) {
  const xs = axis(data, x, xOrder);
  const ys = axis(data, y, yOrder).reverse();
  const cells = new Map(data.map((row) => [`${row[x]}|${row[y]}`, Number(row[value])]));
  const max = Math.max(...cells.values(), 1);
  const total = [...cells.values()].reduce((a, b) => a + b, 0);
  return (
    <div className="oa-heat">
      {yLabel && <div className="oa-heat__ylabel">↑ {yLabel}</div>}
      <div className="oa-heat__grid" style={{ gridTemplateColumns: `max-content repeat(${xs.length}, minmax(0, 1fr))` }}>
        {ys.map((yv) => (
          <div style={{ display: 'contents' }} key={yv}>
            <div className="oa-heat__ytick">{yv}</div>
            {xs.map((xv) => {
              const v = cells.get(`${xv}|${yv}`) ?? 0;
              const t = v / max;
              return (
                <div
                  className={`oa-heat__cell${t > 0.5 ? ' is-dark' : ''}${v === 0 ? ' is-zero' : ''}`}
                  style={{ ['--t' as string]: `${Math.round(Math.sqrt(t) * 100)}%` }}
                  title={`${v} ${unit} · ${xLabel ?? x}: ${xv} · ${yLabel ?? y}: ${yv}`}
                  key={xv}
                >
                  {v === 0 ? '·' : v}
                </div>
              );
            })}
          </div>
        ))}
        <div />
        {xs.map((xv) => (
          <div className="oa-heat__xtick" key={xv}>
            {xv}
          </div>
        ))}
      </div>
      <div className="oa-heat__foot">
        {xLabel && <span className="oa-heat__xlabel">{xLabel} →</span>}
        <span className="oa-heat__scale">
          0 <i /> {max} {unit} per cell · {total} in total
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Every sender paired with every receiver, drawn from sol_fundings rows
// ---------------------------------------------------------------------------

export function CrossDiagram({ data }: { data: Row[] }) {
  const senders = [...new Map(data.map((r) => [String(r.src_wallet), Number(r.src_decrease)])).entries()];
  const receivers = [...new Map(data.map((r) => [String(r.dst_wallet), Number(r.dst_increase)])).entries()];
  const gap = 52;
  const h = Math.max(senders.length, receivers.length) * gap + 12;
  const yOf = (i: number, n: number) => h / 2 + (i - (n - 1) / 2) * gap;
  const W = 150;
  return (
    <div className="oa-cross oa-funding">
      <svg
        className="oa-svg"
        viewBox={`0 0 440 ${h}`}
        role="img"
        aria-label={`${senders.length} wallets lost SOL and ${receivers.length} gained it; every sender is linked to every receiver, ${data.length} rows in total`}
      >
        {senders.map((_s, i) =>
          receivers.map((_r, j) => (
            <line
              className="edge"
              strokeWidth="1.5"
              key={`${i}-${j}`}
              x1={W + 6}
              y1={yOf(i, senders.length)}
              x2={440 - W - 12}
              y2={yOf(j, receivers.length)}
            />
          )),
        )}
        {receivers.map(([addr], j) => (
          <Head key={addr} x={440 - W - 6} y={yOf(j, receivers.length)} />
        ))}
        {senders.map(([addr, amount], i) => (
          <g key={addr}>
            <rect className="node" x={2} y={yOf(i, senders.length) - 19} width={W} height="38" rx="10" />
            <text className="t-ink" x={14} y={yOf(i, senders.length) - 2} fontSize="12.5">
              {shortAddr(addr)}
            </text>
            <text x={14} y={yOf(i, senders.length) + 12} fontSize="11.5">
              −{sol(amount)} SOL
            </text>
          </g>
        ))}
        {receivers.map(([addr, amount], j) => (
          <g key={addr}>
            <rect className="node" x={440 - W - 2} y={yOf(j, receivers.length) - 19} width={W} height="38" rx="10" />
            <text className="t-ink" x={440 - W + 10} y={yOf(j, receivers.length) - 2} fontSize="12.5">
              {shortAddr(addr)}
            </text>
            <text x={440 - W + 10} y={yOf(j, receivers.length) + 12} fontSize="11.5">
              +{sol(amount)} SOL
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}

// ---------------------------------------------------------------------------
// A chain of pass-through wallets, drawn from the pipe example's rows
// ---------------------------------------------------------------------------

export function PipeDiagram({ data }: { data: Row[] }) {
  const hops = [...data].sort((a, b) => Number(b.hop) - Number(a.hop));
  if (hops.length === 0) return null;
  return (
    <ol className="oa-pipe oa-funding">
      <li className="oa-pipe__node">
        <code>{shortAddr(String(hops[0].src_wallet))}</code>
        <span>earliest wallet reached</span>
      </li>
      {hops.map((hop, i) => (
        <li className="oa-pipe__node" key={String(hop.hop)}>
          <div className="oa-pipe__edge">
            <b>{Number(hop.sol).toFixed(3)} SOL</b>
            <span>{String(hop.block_time_utc).slice(5, 16)} UTC</span>
          </div>
          <code>{shortAddr(String(hop.dst_wallet))}</code>
          <span>{i === hops.length - 1 ? 'the token creator' : 'empty before, passes it all on'}</span>
        </li>
      ))}
    </ol>
  );
}
