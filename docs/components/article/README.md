# Article template

Long-form pages under `docs/pages/education/` use this template. The existing
docs pages are untouched: every rule in `article.css` is scoped to `#oa`.

## Writing an article

1. Write the template `docs/articles/education/<slug>.mdx` (title and description in
   frontmatter). Import the blocks you need and wrap the whole body in `<Article>`.
   Leave a blank line after each opening tag so Markdown inside is still parsed.
2. Put every query or script the article shows under `examples/education/<article>/`
   and reference it from the template on a line of its own:

   ```
   {sql example: examples/education/sol_flows/history_depth.sql}
   {python example: examples/education/sol_flows/funding_pipe.py | pinned | view=pipe}
   ```

3. Run `python3 scripts/render_articles.py`. It runs each example against the live
   database, fails if one errors or returns nothing, and writes
   `docs/pages/education/<slug>.mdx` with the code copied 1:1 from the file, a GitHub
   link, and the rows that run returned. Never edit the generated page.
4. Add the page to the `Education` section in `vocs.config.ts`.

Code is never typed into a template, so a page cannot show code that was not run.
Results are saved under `examples/education/results/` with the hash of the code that
produced them. `--offline` renders from those snapshots (and refuses a snapshot whose
code changed); `--reuse` skips examples whose snapshot is still current.

Directive options: `pinned` (fixed historical transaction: the result must not change,
and the snapshot is shown once the rows age out), `rows=N`, `view=heatmap|pipe|cross`
plus the props of that figure.

Python examples import `ocd` (`examples/education/ocd.py`): `query()` for the
connection and retries, `show()` to print rows. Keep everything that is not the point
of the example in that helper.

`sol-topups-vs-funding-vs-transfers.mdx` uses every block and is the reference.

## Blocks (`Article.tsx`)

| Block | Use |
| --- | --- |
| `Kicker`, `Dek`, `Meta` | Header: category line, standfirst, date / read time / level |
| `Definitions` | One-line definition per subject, directly under the header |
| `Term` | Inline subject chip (fixed colour and glyph per subject) |
| `Figure` | Framed figure with title, optional legend, numbered caption |
| `DataTable` | Wraps a Markdown table: caption, sideways scroll, `pin` keeps column 1 in view on phones |
| `Compare` | Subject-by-attribute comparison: table on desktop, stacked blocks on phones |
| `Note`, `PullQuote` | Aside and pull quote |
| `Notice` | Red warning block for data that is deliberately not recorded |
| `Example`, `ExampleResult` | Emitted by the renderer around executed code and its result |
| `Takeaways`, `NextReads`, `ArticleCTA` | Closing blocks |

Subjects (`topup`, `funding`, `transfer`) and their colours are defined in
`Article.tsx` and at the top of `article.css`; add more there for other articles.

## Figures (`figures.tsx`)

`FlowLanes` and `BalanceTimeline` are illustrations. `Heatmap`, `CrossDiagram` and
`PipeDiagram` draw the rows of an executed example (`view=` option). Charts that carry
text are rendered at a wide and a narrow size and swapped by CSS, so labels stay
legible on phones.

Fonts are self-hosted through `@fontsource-variable/*` and loaded from `docs/styles.css`.
