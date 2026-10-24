# Issue #8: Code-split the frontend bundle to clear Vite's chunk-size warning

## Context

`npm run build` emits the whole frontend as one 622 kB chunk, over Vite's 500 kB warning
limit, because no page loads lazily and all third-party code shares the entry chunk. The
fix is frontend-only, with no backend or API client change. Every edit below was applied
to a scratch copy of `tool-upgrade`, and that copy passed the build, tests, lint,
typecheck, and fallow.

## Branch

`issue-8-code-split-the-frontend-bundle-to-clear` — already checked out; PR #9 exists.

The branch starts from `main` at `99bad26`, before PR 3 (`tool-upgrade`) merged. The issue
says to implement after PR 3 merges, so everything below describes `tool-upgrade` at
`52160cf`: the line numbers, the `vite.config.ts` contents, and the measured sizes.
Before implementing, confirm PR 3 has merged and update this branch from `origin/main`.
Of the files below, only `vite.config.ts` and `ai/conventions.md` differ between `main`
and `tool-upgrade`.

## Change

**5 files to edit**: `src_front/src/App.tsx`,
`src_front/src/components/layout/AppShell.tsx`, `vite.config.ts`,
`src_front/src/test/App.test.tsx`, `ai/conventions.md`

### src_front/src/App.tsx — load the pages lazily

- Line 3: import `lazy` and `Suspense` beside `useEffect`.
- Lines 8–10: delete the three static page imports.
- After line 11 (`import { useAuthStore } from './store/auth'`), declare the pages with
  `lazy`.
- Lines 13–22: add two sentences to the `App` JSDoc.
- Lines 30–41: wrap `<Routes>` in `<Suspense fallback={null}>`.

The whole file afterwards:

```tsx
/** @file Route table for the application. */

import { lazy, Suspense, useEffect } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'

import AppShell from './components/layout/AppShell'
import ProtectedRoute from './components/ProtectedRoute'
import { useAuthStore } from './store/auth'

const Home = lazy(() => import('./pages/Home'))
const Login = lazy(() => import('./pages/Login'))
const Register = lazy(() => import('./pages/Register'))

/**
 * Declare every route and the guards around them.
 *
 * On mount the store asks the server who is signed in, so a reload restores
 * the session from the cookie. Everything except the auth pages sits behind
 * {@link ProtectedRoute} inside the {@link AppShell}, and unknown paths
 * redirect to the home page rather than showing a 404. Each page loads on
 * first visit from its own chunk; until it arrives the boundary renders
 * nothing, as {@link ProtectedRoute} does during the session check.
 *
 * @returns The route table.
 */
export default function App() {
    const fetchMe = useAuthStore((s) => s.fetchMe)

    useEffect(() => {
        void fetchMe()
    }, [fetchMe])

    return (
        <Suspense fallback={null}>
            <Routes>
                <Route path="/login" element={<Login />} />
                <Route path="/register" element={<Register />} />
                <Route element={<ProtectedRoute />}>
                    <Route element={<AppShell />}>
                        <Route index element={<Home />} />
                    </Route>
                </Route>
                <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
        </Suspense>
    )
}
```

`fallback={null}` matches `ProtectedRoute`, which returns `null` while the session check
runs (`src_front/src/components/ProtectedRoute.tsx`, `if (isLoading) return null`).

Keep the import factories inline, as shown. `eslint.config.js:64-82` sets
`jsdoc/require-jsdoc` with the context `VariableDeclarator > ArrowFunctionExpression`. A
named factory such as `const loadHome = () => import('./pages/Home')` therefore needs a
JSDoc block, while an arrow passed straight to `lazy` does not.

### src_front/src/components/layout/AppShell.tsx — keep the app bar while a page loads

- After line 4 (`import LogoutIcon from '@mui/icons-material/Logout'`), add
  `import { Suspense } from 'react'`.
- In the `AppShell` JSDoc (lines 73–77), add a paragraph after line 74.
- Line 92: wrap `<Outlet />` in `<Suspense fallback={null}>`.

```tsx
/**
 * Render the navigation bar and an outlet for the active route.
 *
 * The outlet has its own Suspense boundary, so the bar stays on screen while
 * a page's chunk loads.
 *
 * @returns The application shell.
 */
```

```tsx
            <Box component="main" sx={{ flex: 1, minHeight: 0 }}>
                <Suspense fallback={null}>
                    <Outlet />
                </Suspense>
            </Box>
```

Without this inner boundary, `Home` suspending would fall through to the boundary in
`App.tsx`. That boundary sits above `AppShell`, so the fallback would blank the app bar
too. Keep the `Suspense` inside the `main` box: `src_front/src/test/AppShell.test.tsx`
(lines 110–116) expects the outlet's content inside `role="main"`.

### vite.config.ts — group vendor code into three chunks

- After line 2 (`import react from '@vitejs/plugin-react'`) and its blank line, add
  `VENDOR_CHUNKS` and `vendorChunk`.
- Lines 41–44 (`build`): add `rollupOptions.output.manualChunks: vendorChunk` after
  `emptyOutDir: true,`.

```ts
/** Vendor chunk for each top-level `node_modules` directory it collects. */
const VENDOR_CHUNKS: Record<string, string> = {
    react: 'react',
    'react-dom': 'react',
    'react-router': 'react',
    'react-router-dom': 'react',
    scheduler: 'react',
    '@emotion': 'mui',
    '@mui': 'mui',
    'react-transition-group': 'mui',
    stylis: 'mui',
    '@hookform': 'forms',
    'react-hook-form': 'forms',
    zod: 'forms',
}

/**
 * Name the vendor chunk a module belongs to.
 *
 * Vendor chunks change only when dependencies do, so they keep their hashes across
 * deploys that change only application code. Rollup places everything else, and
 * Vite 8 drops the object form of `manualChunks`, so this is the function form.
 *
 * @param id - The module's resolved path.
 * @returns The chunk name, or `undefined` to let Rollup place the module.
 */
function vendorChunk(id: string): string | undefined {
    // Greedy `.*` reaches the last node_modules segment, the package that owns the file.
    const match = /.*\/node_modules\/(@[^/]+|[^/]+)\//.exec(id)
    return match ? VENDOR_CHUNKS[match[1]] : undefined
}
```

```ts
        build: {
            outDir: '../dist',
            emptyOutDir: true,
            rollupOptions: {
                output: {
                    manualChunks: vendorChunk,
                },
            },
        },
```

- Do not use the object form (`manualChunks: { react: [...] }`): Vite 8 removed it.
- Scoped packages are keyed by scope (`@mui`, `@emotion`, `@hookform`), so every package
  under a scope joins its group.
- Packages outside the groups (`axios`, `zustand`, `clsx`, `react-is`, and others) stay
  where Rollup puts them. In the prototype that was the entry chunk or the chunk of the
  group that uses them, and the chunk graph had no cycles: `react` imports nothing, and
  `mui` and `forms` import only `react`.
- `tsconfig.node.json` type-checks this file under `strict`, `noUnusedLocals`, and
  `noUnusedParameters`. The code above passes `tsc -b`.

### src_front/src/test/App.test.tsx — wait for the lazy pages

Line 106 and lines 115–117 query right after `renderAppAtPath`, which now renders the
Suspense fallback first. Await `findByRole` instead:

```tsx
        expect(
            await screen.findByRole('heading', { name: 'Sign in' }),
        ).toBeInTheDocument()
```

```tsx
        expect(
            await screen.findByRole('heading', { name: 'Create account' }),
        ).toBeInTheDocument()
```

Every other case already awaits `findByRole` or `waitFor`, or asserts that nothing
rendered (lines 55–62), which still holds.

### ai/conventions.md — document the convention

The Frontend section is lines 55–70. Insert this bullet after line 65, which ends the
auth-store bullet with "Pages render inside `AppShell`.", and before the Forms bullet at
line 66. With the bullet applied, markdownlint and Prettier both pass:

```markdown
- Pages load through `React.lazy` in `App.tsx`, so each ships in its own chunk, and
  `AppShell` wraps its `Outlet` in `Suspense` so the app bar stays while a page loads.
  `vite.config.ts` groups third-party code into the `react`, `mui`, and `forms` vendor
  chunks; add a large new dependency to one of them in `VENDOR_CHUNKS`.
```

## Parallelism

- **Can be done in parallel**: all five edits. They touch different files, and none
  consumes another's output.
- **Must be sequential**: the `App.tsx` and `App.test.tsx` edits must both be in place
  before the frontend tests run, because the old synchronous assertions fail against
  lazy pages. Verification runs after all five edits.

## No other changes needed

- The pages already default-export their components, which `React.lazy` requires:
  `Home.tsx:10`, `Login.tsx:28`, and `Register.tsx:71` in `src_front/src/pages/`.
  `App.tsx` is their only non-test static importer.
- `src_front/src/test/AppShell.test.tsx`, the page tests, and
  `src_front/src/test/setup.ts`: the prototype passed all 82 frontend tests at 100%
  coverage, with no act or Suspense warnings. `setup.ts` only imports `jest-dom`, so
  nothing fails tests on console output.
- `eslint.config.js`: no rule fires on the module-level `lazy` declarations, and
  `App()` and `AppShell()` stay far under the 50-line function limit.
- `.fallowrc.json`: fallow follows dynamic `import()`.
  `fallow dead-code --trace src_front/src/pages/Home.tsx:default` reports the export as
  used by `App.tsx`, and `fallow audit` reports no issues in the four changed source
  files. It prints one inherited finding, `babel-plugin-react-compiler` as an unused
  devDependency, which comes from PR 3 (fallow does not see the plugin's name string in
  `vite.config.ts`). The audit gate excludes it.
- `ai/project.md:23` (`pages/` - top-level page components) and `README.md:115`
  (`pages/     # Home, Login, Register`) describe `pages/` generically and stay accurate.
- Backend and servers: Flask serves `dist/` through `static_folder='../dist'`
  (`src_back/app.py:80`), and the container nginx serves every built file through
  `try_files` (`docker/nginx.conf:28-30`), so the new chunk files need nothing new.
- `src_front/index.html`: Vite injects the `modulepreload` links for the vendor chunks.
- `/assets/` cache headers in nginx: out of scope; the issue leaves them to a follow-up.

## Verification

1. Run these lanes in parallel: `npm run test`, `npm run lint -- --max-warnings=0`,
   `npm run lint:py`, `npm run lint:md`, `npm run fallow`, `npx prettier --check .`, and
   `npm run typecheck && npm run build`. Keep the last two in one lane, because both run
   `tsc -b`. The `--max-warnings=0` flag and `prettier --check .` match what CI runs.
   Every lane passes, and both suites stay at 100% coverage.
2. The build prints no `(!) Some chunks are larger than 500 kB` warning and no
   circular-chunk warning. The prototype emitted these sizes (hashes will differ):

    | Chunk | Minified | Gzip |
    | --- | ---: | ---: |
    | `react-*.js` | 261.93 kB | 83.11 kB |
    | `mui-*.js` | 211.90 kB | 66.22 kB |
    | `forms-*.js` | 90.38 kB | 26.94 kB |
    | `index-*.js` | 51.47 kB | 20.06 kB |
    | `useAuthFormState-*.js` | 2.34 kB | 1.18 kB |
    | `Register-*.js` | 2.33 kB | 1.17 kB |
    | `Login-*.js` | 1.66 kB | 0.93 kB |
    | `Home-*.js` | 0.63 kB | 0.43 kB |

3. `grep modulepreload dist/index.html` lists only `react-*.js` and `mui-*.js`. No
   `forms-*.js` link appears.
4. The vendor chunks import nothing above them:

    ```text
    for f in dist/assets/{react,mui,forms}-*.js; do
      printf '%s -> ' "${f##*/}"
      grep -oE '(from|import)"\./[^"]+"' "$f" | sort -u | tr '\n' ' '; echo
    done
    ```

    `react` lists nothing, and `mui` and `forms` list only the `react` chunk.
5. Manually: run `npm run docker:up`, then `npm run preview`. `preview` proxies `/api`
   to the `VITE_API_URL` that `scripts/up.sh` writes into `.env`. Open the printed URL
   and check:
    - Register an account, sign out, and sign in; each page renders.
    - While signed in, reload `/` with the Network panel open. The scripts requested are
      `index`, `react`, `mui`, and `Home`, not `forms`, `Login`, or `Register`.
    - With the Network panel throttled, reload `/`. The app bar appears before the
      page body.
6. Expected tradeoff, not a regression: signed in at `/`, the browser loads about 526 kB
   (170 kB gzip). With lazy routes alone, the prototype loaded 454 kB (150 kB gzip). The
   difference is the form-only MUI modules (`TextField` pulls in `Select`, `Menu`,
   `Popover`, and `Modal`), which the `mui` group places in an eagerly loaded chunk. In
   exchange, the 564 kB of vendor chunks survive deploys that change only application
   code. Such a deploy invalidates the 51 kB entry chunk, where lazy routes alone would
   invalidate the 451 kB one.
