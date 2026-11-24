import { createContext, useContext, type ReactNode } from 'react';

/* Building blocks for long-form articles. Styles: ./article.css (loaded
   through docs/styles.css). Wrap the whole MDX body in <Article>. */

export type Subject = 'funding' | 'topup' | 'transfer';

export const SUBJECT_NAMES: Record<Subject, string> = {
  funding: 'Fundings',
  topup: 'Top-ups',
  transfer: 'Token transfers',
};

export function Article({ children }: { children: ReactNode }) {
  return (
    <div id="oa" className="oa">
      {children}
    </div>
  );
}

export function Kicker({ children }: { children: ReactNode }) {
  return <div className="oa-kicker">{children}</div>;
}

export function Dek({ children }: { children: ReactNode }) {
  return <div className="oa-dek">{children}</div>;
}

interface MetaProps {
  published: string;
  readTime?: string;
  level?: string;
}

export function Meta({ published, readTime, level }: MetaProps) {
  return (
    <ul className="oa-meta">
      <li>
        <b>{published}</b>
      </li>
      {readTime && <li>{readTime}</li>}
      {level && <li>{level}</li>}
    </ul>
  );
}

/* Each subject has a fixed shape as well as a fixed colour, so the pairing
   never depends on colour alone. */
export function Glyph({ subject }: { subject: Subject }) {
  const common = {
    className: `oa-glyph oa-${subject}`,
    viewBox: '0 0 16 16',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.75,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    'aria-hidden': true,
  };
  if (subject === 'funding') {
    return (
      <svg {...common}>
        <circle cx="8" cy="8" r="6.25" strokeDasharray="2.6 2.3" />
        <circle cx="8" cy="8" r="2.4" fill="currentColor" stroke="none" />
      </svg>
    );
  }
  if (subject === 'topup') {
    return (
      <svg {...common}>
        <circle cx="8" cy="8" r="6.25" />
        <path d="M8 5.1v5.8M5.1 8h5.8" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <path d="M2 5.25h11.5M10.75 2.5 13.5 5.25 10.75 8" />
      <path d="M14 10.75H2.5M5.25 8 2.5 10.75 5.25 13.5" />
    </svg>
  );
}

export function Term({ subject, children }: { subject: Subject; children?: ReactNode }) {
  return (
    <span className={`oa-term oa-${subject}`}>
      <Glyph subject={subject} />
      {children ?? SUBJECT_NAMES[subject]}
    </span>
  );
}

interface DefinitionsProps {
  label?: string;
  items: { subject: Subject; text: ReactNode }[];
}

export function Definitions({ label = 'The short version', items }: DefinitionsProps) {
  return (
    <section className="oa-defs">
      <div className="oa-defs__label">{label}</div>
      <dl>
        {items.map((item) => (
          <div className={`oa-def oa-${item.subject}`} key={item.subject}>
            <dt>
              <Glyph subject={item.subject} />
              {SUBJECT_NAMES[item.subject]}
            </dt>
            <dd>{item.text}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

interface FigureProps {
  n: number | string;
  title?: string;
  sub?: string;
  legend?: Subject[];
  caption?: ReactNode;
  children: ReactNode;
}

export function Figure({ n, title, sub, legend, caption, children }: FigureProps) {
  return (
    <figure className="oa-figure">
      <div className="oa-figure__frame">
        {(title || legend) && (
          <div className="oa-figure__head">
            <div>
              {title && <div className="oa-figure__title">{title}</div>}
              {sub && <div className="oa-figure__sub">{sub}</div>}
            </div>
            {legend && (
              <ul className="oa-legend">
                {legend.map((s) => (
                  <li key={s}>
                    <Glyph subject={s} />
                    {SUBJECT_NAMES[s]}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
        {children}
      </div>
      {caption && (
        <figcaption>
          <span className="oa-label">Fig. {n}</span>
          <span>{caption}</span>
        </figcaption>
      )}
    </figure>
  );
}

interface DataTableProps {
  n?: number | string;
  title?: string;
  note?: ReactNode;
  /** Keep the first column in view while the table scrolls sideways on phones. */
  pin?: boolean;
  children: ReactNode;
}

/* Wrap a Markdown table: adds a caption, sideways scrolling and edge bleed. */
export function DataTable({ n, title, note, pin, children }: DataTableProps) {
  return (
    <div className={`oa-tablewrap${pin ? ' oa-tablewrap--pin' : ''}`}>
      {title && (
        <div className="oa-tablewrap__cap">
          {n !== undefined && <span className="oa-label">Table {n}</span>}
          <span>{title}</span>
        </div>
      )}
      <div className="oa-tablewrap__scroll">{children}</div>
      {note && <div className="oa-tablewrap__note">{note}</div>}
    </div>
  );
}

interface CompareProps {
  rows: ({ label: string } & Record<Subject, ReactNode>)[];
  subjects?: Subject[];
}

export function Compare({ rows, subjects = ['topup', 'funding', 'transfer'] }: CompareProps) {
  return (
    <div className="oa-compare">
      <table>
        <thead>
          <tr>
            <th scope="col" aria-label="Attribute" />
            {subjects.map((s) => (
              <th scope="col" key={s} className={`oa-${s}`}>
                <span className="oa-compare__subject">
                  <Glyph subject={s} />
                  {SUBJECT_NAMES[s]}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.label}>
              <th scope="row">{row.label}</th>
              {subjects.map((s) => (
                <td key={s}>{row[s]}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="oa-compare__cards">
        {subjects.map((s) => (
          <section className={`oa-compare__card oa-${s}`} key={s}>
            <div className="oa-compare__subject">
              <Glyph subject={s} />
              {SUBJECT_NAMES[s]}
            </div>
            <dl>
              {rows.map((row) => (
                <div key={row.label}>
                  <dt>{row.label}</dt>
                  <dd>{row[s]}</dd>
                </div>
              ))}
            </dl>
          </section>
        ))}
      </div>
    </div>
  );
}

export function Note({ label = 'Note', children }: { label?: string; children: ReactNode }) {
  return (
    <aside className="oa-note">
      <span className="oa-label">{label}</span>
      {children}
    </aside>
  );
}

/* A warning the reader must not miss: data that is deliberately not recorded. */
export function Notice({ label = 'Important', children }: { label?: string; children: ReactNode }) {
  return (
    <aside className="oa-notice" role="note">
      <span className="oa-label">
        <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">
          <path d="M8 1.2 15.2 14H.8L8 1.2Z" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
          <path d="M8 6v3.6M8 11.6v.4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        </svg>
        {label}
      </span>
      {children}
    </aside>
  );
}

interface ExampleMeta {
  file: string;
  href: string;
  ranAt: string;
  rowCount: number;
  shown: number;
  snapshot: boolean;
}

const ExampleContext = createContext<ExampleMeta | null>(null);

/* Emitted by scripts/render_articles.py around every executed example:
   the code copied from the repository, then <ExampleResult> with its output. */
export function Example({ children, ...meta }: ExampleMeta & { children: ReactNode }) {
  const name = meta.file.split('/').pop();
  return (
    <ExampleContext.Provider value={meta}>
      <section className="oa-example">
        <header className="oa-example__head">
          <span className="oa-example__file">
            <span className="oa-label">{meta.file.endsWith('.py') ? 'Python' : 'SQL'}</span>
            <code>{name}</code>
          </span>
          <a href={meta.href} target="_blank" rel="noopener noreferrer">
            Source on GitHub <span aria-hidden="true">↗</span>
          </a>
        </header>
        {children}
      </section>
    </ExampleContext.Provider>
  );
}

export function ExampleResult({ children }: { children: ReactNode }) {
  const meta = useContext(ExampleContext);
  const rows = meta
    ? meta.shown < meta.rowCount
      ? `first ${meta.shown} of ${meta.rowCount.toLocaleString('en-US')} rows`
      : `${meta.rowCount.toLocaleString('en-US')} ${meta.rowCount === 1 ? 'row' : 'rows'}`
    : '';
  return (
    <div className="oa-result">
      <div className="oa-result__head">
        <span className="oa-label">Result</span>
        {meta && (
          <span className="oa-result__meta">
            {rows} · {meta.snapshot ? 'saved from the run on' : 'this code ran on'} {meta.ranAt}
          </span>
        )}
      </div>
      <div className="oa-result__body">{children}</div>
    </div>
  );
}

export function PullQuote({ children, cite }: { children: ReactNode; cite?: ReactNode }) {
  return (
    <figure className="oa-pull">
      <blockquote>{children}</blockquote>
      {cite && <figcaption>{cite}</figcaption>}
    </figure>
  );
}

interface TakeawaysProps {
  title?: string;
  items: ReactNode[];
}

export function Takeaways({ title = 'Key takeaways', items }: TakeawaysProps) {
  return (
    <section className="oa-takeaways">
      <span className="oa-label">Summary</span>
      <p className="oa-takeaways__title">{title}</p>
      <ul>
        {items.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>
    </section>
  );
}

interface NextReadsProps {
  label?: string;
  items: { title: string; desc?: string; href: string }[];
}

export function NextReads({ label = 'Keep reading', items }: NextReadsProps) {
  return (
    <nav className="oa-next" aria-label={label}>
      <div className="oa-label">{label}</div>
      <div className="oa-next__grid">
        {items.map((item) => (
          <a href={item.href} key={item.href}>
            <span className="oa-next__title">{item.title}</span>
            <span className="oa-next__arrow" aria-hidden="true">
              →
            </span>
            {item.desc && <span className="oa-next__desc">{item.desc}</span>}
          </a>
        ))}
      </div>
    </nav>
  );
}

interface ArticleCTAProps {
  title?: string;
  sub?: string;
  button?: string;
  href?: string;
}

export function ArticleCTA({
  title = 'Run it on the full dataset',
  sub = 'Direct ClickHouse access · $200/month per chain · one-week free trial',
  button = 'Start free trial',
  href = 'https://forms.gle/b5Fuuns7jcA3nHKv5',
}: ArticleCTAProps) {
  return (
    <div className="oa-cta">
      <div>
        <div className="oa-cta__title">{title}</div>
        <div className="oa-cta__sub">{sub}</div>
      </div>
      <a className="oa-cta__btn" href={href} target="_blank" rel="noopener noreferrer">
        {button} <span aria-hidden="true">→</span>
      </a>
    </div>
  );
}
