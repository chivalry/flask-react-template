# Issue #20: Add CSV export and file download helpers

## Context

Two apps export CSV (ts-subscription-site `src_back/api/admin.py:381-440`, ranch-tracker
`src_back/api/transactions.py:89-119`) and two save a response body in the browser
(invoicing `src_front/src/api/invoices.ts:123-136`, ranch-tracker
`src_front/src/api/downloads.ts`). Only ranch-tracker's CSV guards against spreadsheet
formula injection, and only in the three columns it names by hand. Each download helper
repeats the same object-URL steps. This adds `csv_response()` and `downloadFile()` so the
next app starts from the guarded version.

Nothing in the template exports or downloads yet, so their tests are their only callers.
fallow accepts that: `.fallowrc.json` makes every test file an entry point.

An adversarial review ran the plan's Python through Ruff, Ruff format, pydoclint,
basedpyright, and pytest on Python 3.13.18 and 3.12.11 (20 tests, every new line covered),
and its TypeScript through ESLint, Prettier, `tsc`, and real Vitest 4.1.8 with the v8
provider (327 tests, 100% on all four thresholds). It drove the real XHR adapter against
the real Flask app and served the `BytesIO` body through gunicorn 23's request code. Its
findings are folded in below. It could not run `fallow audit`, Docker, a real browser, or
the full pytest suite; Verification runs them.

What exists to build on:

- `src_back/utils.py` holds the shared response helpers, and
  `src_back/tests/test_utils.py` tests them in `# -- name ---` sections.
- `src_front/src/api/client.ts:58-64` is `surfaceApiError`, which copies the server's
  `{ error }` text onto `error.message`, and `:75-81` is `reportLostSession`, which reads
  only the status and URL.
- `src_front/src/test/api/client.test.ts:16-36` is `respondWith`, an adapter that runs the
  real interceptors without a network.
- `src_front/src/hooks/useApiError.ts` shows `error.message`, which is how a caller will
  show a failed download.

Choices this plan makes:

- `csv_response` returns `flask.send_file(...)`, not a hand-built `Response`. It is still
  a `Response`, with the type and disposition the issue names. All three sibling apps
  write `Content-Disposition` as a raw f-string, and `Headers.set` leaves a non-ASCII name
  raw too, which gunicorn refuses for a name beyond Latin-1 with `InvalidHeader`.
  `send_file` writes `filename=Resume.csv; filename*=UTF-8''R%C3%A9sum%C3%A9.csv`, and a
  name holding a newline raises `ValueError`. It needs a request context, which a handler
  always has, and it sets `direct_passthrough`, so the tests clear that before reading
  the body. It also sends `Cache-Control: no-cache` and `Accept-Ranges: bytes`, both
  harmless here: neither nginx config caches, and an XHR sends no `Range`.
- `encode('utf-8-sig')` writes the byte order mark, so the source holds no invisible
  character for a cleanup to remove.
- Numbers stay numbers. The issue says "any cell", but its reference guards text alone,
  and `'-5.00` is text a spreadsheet's `SUM` skips. `_neutralize_formula` passes numbers
  and `None` through and checks everything else as its `str()`, so a `date` stays as it
  was and an object whose text starts with `=` is caught. Text that only looks numeric,
  such as a schema's `as_string=True` dump of a `Decimal`, gains the quote, so
  `ai/conventions.md` says to pass model values.
- The header row goes through the same guard, since it is now a parameter.
- `downloadFile` rejects on failure, as every API function does, so a caller shows the
  message through `useApiError`. ranch-tracker's `alert()` and boolean do not fit that.
- `path` is relative to the API base, like every call through the client. `/uploads` sits
  outside it (`src_back/app.py:379`), so `downloadFile('/uploads/x.png', ...)` would
  request `/api/uploads/x.png`. ranch-tracker's `fetch` could do that; `ai/conventions.md`
  says a stored file needs a plain link instead.
- The anchor stays detached, as in invoicing, ranch-tracker, and FileSaver.js.
- The object URL is revoked 40 seconds after the click, not at once. The siblings
  disagree: invoicing revokes synchronously, and ranch-tracker moved to
  `setTimeout(..., 0)` with no reason recorded. WebKit bug 211234 lost downloads on iOS 13
  when the URL was revoked at once, and WebKit fixed that in r262085 (bug 212279, May
  2020). FileSaver.js still waits 40 seconds. Nothing else can reach the URL, so a late
  revoke costs only the memory the blob holds, and it has no failure mode. Verification
  checks a real WebKit and leaves Safari itself to a manual step.

Decisions made with Chuck while planning, beyond the issue text:

- The guard covers OWASP's current list: the issue's six characters plus line feed and
  the four full-width forms, which ranch-tracker's guard lets through.
- `surfaceApiError` reads the `{ error }` text out of a blob body, so the client's
  documented contract holds for every blob request. `client.ts` was not in the issue, and
  no sibling does this.
- `downloadFile` lifts the client's 15-second timeout, which covers the whole transfer.
  Only the browser's limit goes: gunicorn's 30-second sync worker limit and nginx's
  60-second read limit still end a request the server cannot finish.
- During implementation, the mutation pass found that weakening `surfaceApiError`'s
  `typeof` check survived, which matters now that the client parses JSON from whatever a
  blob holds. Chuck approved adding `'{"error":42}'` to the blob cases in
  `client.test.ts`, and left the detached anchor and the interceptor order unpinned:
  nothing a user sees depends on the first, and the second changes nothing.

Known limit, stated in the docstring and `ai/conventions.md`: OWASP says checking the
first character is not sufficient, and no quoting fixes this. Where a spreadsheet splits
on `;`, the cell `x;=1+1` still opens as two, with `=1+1` starting the second. The guard
also does not survive every path through Excel, which OWASP warns can drop the quote when
a file is saved and reopened. So it neutralizes the common attack, and the docs do not
call the file safe.

## Branch

`issue-20-add-csv-export-and-file-download-helpers` — already checked out; PR #54 exists.

## Change

**9 files**, 2 of them new: `src_back/utils.py`, `src_back/tests/test_utils.py`,
`src_front/src/api/downloads.ts` (new), `src_front/src/test/api/downloads.test.ts` (new),
`src_front/src/api/client.ts`, `src_front/src/test/api/client.test.ts`,
`ai/conventions.md`, `ai/project.md`, `README.md`.

Line numbers are those of the files before any edit, so place each change by its quoted
neighbor. In Python, `npm run format:py` sets the blank lines around top-level
definitions.

### src_back/utils.py — `csv_response`

Line 1, the module docstring's summary, becomes:

```python
"""Shared helpers for error envelopes, pagination, parsing, uploads, and CSV downloads.
```

The imports at lines 8-17 become:

```python
import csv
import functools
import math
import uuid as uuid_lib
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from io import BytesIO, StringIO
from itertools import chain
from pathlib import Path
from typing import Any, cast

import filetype
from flask import Response, current_app, jsonify, request, send_file
```

After line 38 (`_QUOTE_TRANSLATION = ...`), add:

```python
_FORMULA_PREFIXES = tuple('=+-@\t\r\n＝＋－＠')
"""What a spreadsheet may read as the start of a formula, from OWASP's CSV page.

The last four are the full-width forms of ``=``, ``+``, ``-``, and ``@``, which some
regional settings treat the same way.
"""
```

After `delete_upload` (line 463), before `admin_required`, add:

```python
def _neutralize_formula(cell: object) -> object:
    """Keep a spreadsheet from reading a CSV cell as a formula.

    A leading single quote makes a spreadsheet treat the cell as text. Numbers and blanks
    pass through: neither can carry a formula, and the quote would turn a negative amount
    into text that ``SUM`` skips. Anything else is checked as its ``str()``.

    Args:
        cell: One value of a row.

    Returns:
        The value to hand to ``csv.writer``.
    """
    if cell is None or isinstance(cell, int | float | Decimal):
        return cell
    text = str(cell)
    return f"'{text}" if text.startswith(_FORMULA_PREFIXES) else text


def csv_response(
    rows: Iterable[Sequence[object]], filename: str, header: Sequence[str]
) -> Response:
    """Build a CSV attachment with formula text neutralized.

    Every cell goes through :func:`_neutralize_formula`, so text a user typed, such as
    ``=HYPERLINK(...)``, opens as text; pass numbers as numbers, because text that only
    looks numeric gains the quote. Only the start of a cell is checked, so a spreadsheet
    that splits on ``;`` still opens ``x;=1+1`` as two cells. The ``utf-8-sig`` encoding
    adds the byte order mark, without which Excel reads the body in the local code page.
    ``send_file`` writes the attachment header, which keeps a filename beyond ASCII
    legal, so this must run inside a request.

    Args:
        rows: The data rows, in order, each a sequence of cells.
        filename: The name browsers save the file under.
        header: The column names, written as the first row.

    Returns:
        The response, of type ``text/csv; charset=utf-8``, with the file attached.
    """
    buffer = StringIO()
    writer = csv.writer(buffer)
    for row in chain([header], rows):
        writer.writerow([_neutralize_formula(cell) for cell in row])
    return send_file(
        BytesIO(buffer.getvalue().encode('utf-8-sig')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=filename,
    )
```

### src_back/tests/test_utils.py — `csv_response`

Line 1 gains `import csv` above `import io`. Line 3 becomes
`from collections.abc import Callable, Iterable, Sequence`, `from decimal import Decimal`
goes after line 4, and `csv_response,` joins the `src_back.utils` import after `conflict,`
(line 26).

After line 467 (`assert outside.exists()`), before `# -- admin_required`, add:

```python
# -- csv_response -------------------------------------------------------------


class _FormulaText:
    def __str__(self) -> str:
        return '=SUM(A1)'


def _csv_export(
    app: Flask,
    rows: Iterable[Sequence[object]],
    *,
    header: Sequence[str] = ('Note',),
    filename: str = 'notes.csv',
) -> Response:
    with app.test_request_context():
        response = csv_response(rows, filename, header)
    # send_file leaves the body for the server to send; a test reads it here instead.
    response.direct_passthrough = False
    return response


def _csv_cells(response: Response) -> list[list[str]]:
    text = response.get_data().decode('utf-8-sig')
    return list(csv.reader(io.StringIO(text, newline='')))


def test_csv_response_writes_a_byte_order_mark_then_the_header_and_rows(
    app: Flask,
) -> None:
    response = _csv_export(app, [['Ada', 'Hi']], header=('Name', 'Note'))
    assert response.get_data() == b'\xef\xbb\xbfName,Note\r\nAda,Hi\r\n'


def test_csv_response_attaches_utf_8_csv_under_the_filename(app: Flask) -> None:
    response = _csv_export(app, [], filename='accounts.csv')
    assert response.headers['Content-Type'] == 'text/csv; charset=utf-8'
    assert response.headers['Content-Disposition'] == 'attachment; filename=accounts.csv'


def test_csv_response_encodes_a_filename_beyond_ascii(app: Flask) -> None:
    response = _csv_export(app, [], filename='Résumé.csv')
    assert response.headers['Content-Disposition'] == (
        "attachment; filename=Resume.csv; filename*=UTF-8''R%C3%A9sum%C3%A9.csv"
    )


@pytest.mark.parametrize(
    'cell',
    [
        '=SUM(A1)',
        '+1',
        '-1',
        '@SUM(A1)',
        '\tSUM(A1)',
        '\rSUM(A1)',
        '\nSUM(A1)',
        '＝SUM(A1)',
        '＋1',
        '－1',
        '＠SUM(A1)',
    ],
)
def test_csv_response_quotes_text_a_spreadsheet_could_run(app: Flask, cell: str) -> None:
    assert _csv_cells(_csv_export(app, [[cell]])) == [['Note'], [f"'{cell}"]]


def test_csv_response_quotes_the_header_too(app: Flask) -> None:
    assert _csv_cells(_csv_export(app, [], header=('=Note',))) == [["'=Note"]]


def test_csv_response_leaves_numbers_numeric_and_blanks_empty(app: Flask) -> None:
    response = _csv_export(app, [[-1, -1.5, Decimal('-5.00'), 0, None, '']])
    assert _csv_cells(response)[1] == ['-1', '-1.5', '-5.00', '0', '', '']


def test_csv_response_checks_any_other_value_as_text(app: Flask) -> None:
    response = _csv_export(app, [[date(2026, 10, 31), _FormulaText()]])
    assert _csv_cells(response)[1] == ['2026-10-31', "'=SUM(A1)"]


def test_csv_response_leaves_a_formula_character_later_in_a_cell(app: Flask) -> None:
    assert _csv_cells(_csv_export(app, [['a=b']]))[1] == ['a=b']


def test_csv_response_escapes_separators_and_keeps_text_beyond_ascii(app: Flask) -> None:
    rows = [['x,y', 'q"r', 'Résumé']]
    assert _csv_cells(_csv_export(app, rows))[1] == ['x,y', 'q"r', 'Résumé']


def test_csv_response_takes_rows_from_a_generator(app: Flask) -> None:
    rows = ([name] for name in ('Ada', 'Grace'))
    assert _csv_cells(_csv_export(app, rows)) == [['Note'], ['Ada'], ['Grace']]
```

### src_front/src/api/downloads.ts — new

```ts
/**
 * @file Saves a file from the API in the browser, under a name the app chooses.
 *
 * The request goes through the axios client rather than a plain link, so it carries the
 * session, a 401 still reports a lost session, and a failure rejects with the server's
 * `{ error }` text for the caller to show.
 */

import client from './client'

/**
 * How long an object URL outlives its click, in milliseconds.
 *
 * WebKit has lost downloads whose URL was revoked at once. Nothing else can reach the
 * URL, so revoking late costs only the memory it holds; FileSaver.js waits as long.
 */
const REVOKE_DELAY_MS = 40_000

/**
 * Fetch a file from the API and save it in the browser.
 *
 * The request sets no timeout, because the client's 15 seconds would cover the whole
 * transfer and abort a large file partway.
 *
 * @param path - The endpoint, relative to the API base, such as `/v1/users/export.csv`.
 * @param filename - The name the browser saves the file under.
 * @returns A promise that resolves once the file is handed to the browser; it rejects
 *   when the request fails.
 */
export async function downloadFile(path: string, filename: string): Promise<void> {
    const { data } = await client.get<Blob>(path, { responseType: 'blob', timeout: 0 })
    const url = URL.createObjectURL(data)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = filename
    anchor.click()
    setTimeout(() => {
        URL.revokeObjectURL(url)
    }, REVOKE_DELAY_MS)
}
```

### src_front/src/test/api/downloads.test.ts — new

`URL.createObjectURL` exists under Vitest's jsdom environment, so it can be spied on, as
the issue says. Clicking a real anchor in jsdom would try to navigate, so `click` is
replaced. The anchor test records what the anchor held at the moment of the click,
because reading it afterward passes an anchor clicked before it was set up, and it
compares the blob with `toBe`, because `toHaveBeenCalledWith` treats all Blobs as equal.

```ts
/** @file downloadFile saves a response body through a temporary anchor. */

import type { AxiosResponse } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import client from '../../api/client'
import { downloadFile } from '../../api/downloads'

vi.mock('../../api/client')

const OBJECT_URL = 'blob:http://localhost/export'
const PATH = '/v1/users/export.csv'
const FILENAME = 'accounts.csv'
const body = new Blob(['a,b\r\n'], { type: 'text/csv' })

describe('downloadFile', () => {
    beforeEach(() => {
        vi.useFakeTimers()
        vi.resetAllMocks()
        vi.mocked(client.get).mockResolvedValue({ data: body } as AxiosResponse)
        vi.spyOn(URL, 'createObjectURL').mockReturnValue(OBJECT_URL)
        vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
        vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
        vi.spyOn(document, 'createElement')
    })

    afterEach(() => {
        vi.useRealTimers()
        vi.restoreAllMocks()
    })

    it('fetches the file as a blob, without the client timeout', async () => {
        await downloadFile(PATH, FILENAME)

        expect(client.get).toHaveBeenCalledExactlyOnceWith(PATH, {
            responseType: 'blob',
            timeout: 0,
        })
    })

    it('clicks one anchor that saves the body under the filename', async () => {
        const clicked: { href: string; download: string }[] = []
        vi.mocked(HTMLAnchorElement.prototype.click).mockImplementation(function (
            this: HTMLAnchorElement,
        ) {
            clicked.push({ href: this.href, download: this.download })
        })

        await downloadFile(PATH, FILENAME)

        expect(URL.createObjectURL).toHaveBeenCalledOnce()
        expect(vi.mocked(URL.createObjectURL).mock.calls[0][0]).toBe(body)
        expect(document.createElement).toHaveBeenCalledExactlyOnceWith('a')
        expect(clicked).toEqual([{ href: OBJECT_URL, download: FILENAME }])
    })

    it('revokes the object URL once, forty seconds after the click', async () => {
        await downloadFile(PATH, FILENAME)

        vi.advanceTimersByTime(39_999)
        expect(URL.revokeObjectURL).not.toHaveBeenCalled()

        vi.advanceTimersByTime(1)
        expect(URL.revokeObjectURL).toHaveBeenCalledExactlyOnceWith(OBJECT_URL)
    })

    it('saves nothing and rejects when the request fails', async () => {
        const failure = new Error('Admin access required.')
        vi.mocked(client.get).mockRejectedValue(failure)

        await expect(downloadFile(PATH, FILENAME)).rejects.toBe(failure)

        expect(URL.createObjectURL).not.toHaveBeenCalled()
        expect(HTMLAnchorElement.prototype.click).not.toHaveBeenCalled()
    })
})
```

### src_front/src/api/client.ts — read the error text from a blob

With `responseType: 'blob'` the failed body arrives as a `Blob`, so `data.error` is
`undefined` and `error.message` would stay axios's `Request failed with status code 403`.

Lines 8-10 of the file comment become:

```ts
 * Two response interceptors run on every failure: one copies the backend's `{ error }`
 * text into `error.message`, from a blob body too, the other reports a lost session to
 * whoever registered through {@link setUnauthorizedHandler}.
```

Lines 52-64 become:

```ts
/**
 * Read the body of a failed response, which a blob request receives as a blob.
 *
 * A blob that is not JSON, such as a proxy's HTML error page, counts as no body.
 *
 * @param data - The response body, if there was one.
 * @returns The parsed body, or undefined when there is none to read.
 */
async function readErrorBody(
    data?: ApiErrorBody | Blob,
): Promise<ApiErrorBody | undefined> {
    if (!(data instanceof Blob)) {
        return data
    }
    try {
        return JSON.parse(await data.text()) as ApiErrorBody
    } catch {
        return undefined
    }
}

/**
 * Promote the backend's `{ error }` text to `error.message` so forms can show it.
 *
 * @param error - The rejection axios produced for a failed request.
 * @returns A promise rejected with the same error.
 */
export async function surfaceApiError(
    error: AxiosError<ApiErrorBody | Blob>,
): Promise<never> {
    const body = await readErrorBody(error.response?.data)
    const message = body?.error
    if (typeof message === 'string') {
        error.message = message
    }
    return Promise.reject(error)
}
```

### src_front/src/test/api/client.test.ts — blob error bodies

In `describe('surfaceApiError')`, after the test `leaves the message alone when the body
carries no error text`, which ends at line 90, add:

```ts
    it('reads the error text from a blob body, as a download receives it', async () => {
        const error = {
            message: 'Request failed with status code 403',
            response: { data: new Blob(['{"error":"Admin access required."}']) },
        } as AxiosError<Blob>

        await expect(surfaceApiError(error)).rejects.toBe(error)
        expect(error.message).toBe('Admin access required.')
    })

    it.each(['<html>Bad gateway</html>', 'null', '{}', '{"error":42}'])(
        'leaves the message alone when a blob body holds %s',
        async (text) => {
            const error = {
                message: 'Request failed with status code 502',
                response: { data: new Blob([text]) },
            } as AxiosError<Blob>

            await expect(surfaceApiError(error)).rejects.toBe(error)
            expect(error.message).toBe('Request failed with status code 502')
        },
    )
```

In `describe('response interceptors')`, after the test `surface the error text and report
a lost session on a 401`, add:

```ts
    it('read a blob error body and still report a lost session', async () => {
        await expect(
            client.get('/v1/things', {
                responseType: 'blob',
                adapter: respondWith(401, new Blob(['{"error":"Session expired."}'])),
            }),
        ).rejects.toThrow('Session expired.')

        expect(handler).toHaveBeenCalledTimes(1)
    })
```

### ai/conventions.md — the two conventions

After line 129, the end of the `Image uploads` bullet in API Responses, add:

```markdown
- A CSV export answers with `csv_response(rows, filename, header)` from `utils.py`, never
  a hand-built response. It writes the byte order mark Excel needs and puts a single
  quote before text that starts a cell with a formula character, so a note a user typed,
  such as `=HYPERLINK(...)`, opens as text. It checks only the start of a cell: where a
  spreadsheet splits on `;`, a cell holding `x;=1+1` still opens as two. Numbers pass
  through, which keeps a negative amount a number, so pass model values rather than a
  schema's dump: a `Decimal` field with `as_string=True` dumps `-5.00` as text, which
  gains the quote.
```

After line 136, the end of the axios client bullet in Frontend, add:

```markdown
- A file download goes through `downloadFile(path, filename)` from `api/downloads.ts`. Its
  `path` is relative to the API base, like every call through the client, so a stored
  file under `/uploads`, outside that base, needs a plain link. Going through the client
  keeps the session handling: a 401 reports a lost session, and a failure rejects with
  the server's `error` text, which `surfaceApiError` reads out of the blob, for
  `useApiError` to show. It sets no timeout, because the client's 15 seconds would cover
  the whole transfer; gunicorn's 30-second worker limit still applies to building the
  file, so an export that needs longer fails with a 502 from nginx.
```

### ai/project.md — the two inventories

Lines 32-33, `utils.py`, become:

```markdown
    - `utils.py` - error envelopes, pagination in memory and in SQL, query-string
      parsing, quote folding, upload validation, CSV responses
```

Line 35, the frontend's `api/`, becomes:

```markdown
    - `api/` - axios client, the `resource()` factory, `downloadFile()`, and typed API
      modules
```

### README.md — the layout

Line 217 becomes:

```text
│   ├── utils.py       # Error envelopes, pagination, parsing, upload checks, CSV
```

and line 225 becomes:

```text
│       ├── api/       # Axios client, resource(), downloadFile(), typed API modules
```

## Parallelism

- **Can be done in parallel**:
    - Group A, the backend: `src_back/utils.py`, `src_back/tests/test_utils.py`.
    - Group B, the frontend: `src_front/src/api/downloads.ts`,
      `src_front/src/test/api/downloads.test.ts`, `src_front/src/api/client.ts`,
      `src_front/src/test/api/client.test.ts`.
    - Group C, the documentation: `ai/conventions.md`, `ai/project.md`, `README.md`.
- **Must be sequential**: nothing across the groups. Within each code group, the source
  comes before its test run.

## No other changes needed

- No endpoint and no button: nothing in the template exports yet, and the issue asks for
  none. `.fallowrc.json` counts the test as `downloadFile`'s importer.
- `src_front/src/hooks/useApiError.ts` already shows `error.message`.
- `reportLostSession` reads only the status and URL, so it needs nothing for a blob.
- `tools.md`: `csv` is one more standard-library module, with no alternative weighed, so
  it has no entry to write, unlike `smtplib`.
- `pyproject.toml`, `vite.config.ts`, and `.fallowrc.json`: their gates already cover the
  new code.
- nginx and the Compose files: a CSV body is an ordinary response.

## Verification

1. Targeted, while editing: `.venv/bin/python -m pytest src_back/tests/test_utils.py
   --no-cov`, and `npx vitest run src_front/src/test/api/downloads.test.ts
   src_front/src/test/api/client.test.ts`.
2. At the end, in parallel: `npm run test`, `npm run lint -- --max-warnings=0`, and
   `npm run lint:py`; then `npm run typecheck`, `npx fallow audit`, `npm run lint:md`, and
   `npx prettier --check .`.
3. In real browsers, on a throwaway Compose project so the dev database stays untouched.
   Take sorted listings of `docker ps -a`, `docker images`, and `docker volume ls`, write
   a scratch env file with its own `COMPOSE_PROJECT_NAME` and free ports, run
   `docker compose --env-file <scratch> -p <project> up --build -d`, and install
   Playwright 1.64.1 in a scratch directory, driving Chrome (`channel: 'chrome'`) and
   Playwright's WebKit and Firefox builds. In each browser, open the frontend and run
   these in the page, through `page.addScriptTag({ type: 'module', ... })` if `import()`
   inside `page.evaluate` fails there:
    - `import('/src/api/downloads.ts').then((m) => m.downloadFile('/health',
      'health.json'))`: Playwright's `download` event names `health.json`, and the saved
      file holds the health JSON.
    - `import('/src/api/downloads.ts').then((m) => m.downloadFile('/v1/users',
      'users.json')).catch((e) => e.message)`, signed out: it answers `Unauthorized`, the
      server's text, not axios's status message, and no download starts.
4. In Safari, by hand, before the teardown, since Playwright's WebKit only approximates
   it: ask Chuck to run the first line above in Safari's console on the same stack. The
   file lands in Downloads, once Safari has been told to allow downloads from the site.
5. Tear down with `docker compose --env-file <scratch> -p <project> down -v --rmi local`,
   never without `-p`: `.env` names the dev project, whose volume holds real data. Delete
   the scratch env file and compare the sorted listings.
