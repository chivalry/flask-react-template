"""Fail the build when a Python function is too tall to fit on one screen.

Ruff has no physical-line function-length rule -- its closest relatives count
statements, branches, or complexity, none of which track how many rows a
function actually occupies in an editor. This check closes that gap so the
Python side matches ESLint's ``max-lines-per-function`` on the TypeScript side.

Length is measured in physical lines from the ``def`` line through the last
line of the body, docstrings and blank lines included, because every one of
those occupies a row on screen. Decorators are excluded: they sit above the
``def`` and ``ast`` reports ``lineno`` at the ``def`` itself.
"""

import argparse
import ast
import pathlib
import sys

MAX_FUNCTION_LINES = 50

EXCLUDED_DIRECTORY_NAMES = frozenset(
    {
        '.git',
        '.pytest_cache',
        '.ruff_cache',
        '.venv',
        '__pycache__',
        'dist',
        'htmlcov',
        'migrations',
        'node_modules',
    }
)


def measure_functions(
    path: pathlib.Path,
) -> list[tuple[pathlib.Path, int, str, int]]:
    """Measure the physical length of every function in one module.

    ``ast.walk`` descends into nested functions as well, which is intended: a
    closure occupies the same screen rows as anything else.

    Args:
        path: The Python file to parse.

    Returns:
        One ``(path, line, name, length)`` entry per function in the file.
    """
    tree = ast.parse(path.read_text(encoding='utf-8'))
    return [
        (path, node.lineno, node.name, (node.end_lineno or node.lineno) - node.lineno + 1)
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]


def iter_python_files(targets: list[str]) -> list[pathlib.Path]:
    """Expand command-line targets into the set of files to check.

    Directories are walked recursively; explicit file paths are taken as given
    so ``lint-staged`` can hand this script the names it has staged.

    Args:
        targets: Directory or file paths supplied on the command line.

    Returns:
        Sorted, de-duplicated paths to every Python file worth checking.
    """
    found: set[pathlib.Path] = set()
    for target in targets:
        path = pathlib.Path(target)
        if path.is_dir():
            found.update(
                candidate
                for candidate in path.rglob('*.py')
                if not EXCLUDED_DIRECTORY_NAMES.intersection(candidate.parts)
            )
        elif path.suffix == '.py' and not EXCLUDED_DIRECTORY_NAMES.intersection(
            path.parts
        ):
            found.add(path)
    return sorted(found)


def find_violations(
    paths: list[pathlib.Path], max_lines: int
) -> list[tuple[pathlib.Path, int, str, int]]:
    """Measure every function in every file and collect the over-budget ones.

    Args:
        paths: Python files to parse.
        max_lines: The inclusive physical-line budget for one function.

    Returns:
        Violations as ``(path, line, name, length)``, longest function first.
    """
    violations = [
        measurement
        for path in paths
        for measurement in measure_functions(path)
        if measurement[3] > max_lines
    ]
    return sorted(violations, key=lambda violation: violation[3], reverse=True)


def main() -> int:
    """Check the requested paths and report any function that is too tall.

    Returns:
        ``0`` when every function fits the budget, ``1`` otherwise.
    """
    summary = __doc__.splitlines()[0] if __doc__ else 'Check Python function length.'
    parser = argparse.ArgumentParser(description=summary)
    parser.add_argument('targets', nargs='+', help='Files or directories to check.')
    parser.add_argument(
        '--max-lines',
        type=int,
        default=MAX_FUNCTION_LINES,
        help=f'Physical-line budget per function (default: {MAX_FUNCTION_LINES}).',
    )
    args = parser.parse_args()

    violations = find_violations(iter_python_files(args.targets), args.max_lines)
    if not violations:
        return 0

    print(f'Functions longer than {args.max_lines} lines:', file=sys.stderr)
    for path, line, name, length in violations:
        print(f'  {path}:{line}  {name}  ({length} lines)', file=sys.stderr)
    print(f'\n{len(violations)} function(s) over budget.', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
