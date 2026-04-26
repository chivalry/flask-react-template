# Potential Improvements

## `.vscode/settings.json`

The current settings file is minimal (only `files.associations`). The
following additions would improve the local development experience:

- **`editor.formatOnSave: true`** — Runs the formatter automatically on
  every save, enforcing code style without a manual step and reducing
  noise in diffs.

- **`editor.defaultFormatter: "esbenp.prettier-vscode"`** — Sets Prettier
  as the default formatter for JS/TS/JSON/CSS files. Requires the
  `esbenp.prettier-vscode` extension.

- **`[python].editor.defaultFormatter: "charliermarsh.ruff"`** — Overrides
  the default for Python files. Ruff is already in `requirements.txt`;
  this wires it into VS Code's save behavior. Requires the
  `charliermarsh.ruff` extension.

- **`ruff.enable: true`** — Explicitly enables Ruff extension diagnostics
  (inline squiggles for lint errors).

- **`eslint.validate: [javascript, javascriptreact, typescript,
  typescriptreact]`** — Ensures the ESLint extension lints `.ts` and
  `.tsx` files inline, not just plain JS.

- **`files.exclude` for `__pycache__`, `.pytest_cache`, `node_modules`** —
  Hides these directories from the VS Code file explorer and search.
  They are already in `.gitignore` but VS Code shows them unless
  explicitly excluded.
