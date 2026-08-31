# ALWeaver Agent Guidelines

## Priority & Architecture
- **Primary interface**: `/al/editor` (SPA & `/al/editor/api/*`). The legacy wizard interview (`assembly_line.yml`) is secondary.
- **Design reference**: See `architecture.md`.

## Commands
- **Run tests**: `uv run pytest` (from repo root; or `uv run pytest path/to/test.py`)
- **Format & Typecheck**:
  - Python: `uv run black .` and `uv run mypy . --exclude '^build/' --explicit-package-bases`
  - JavaScript: `npm run check` (Prettier, ESLint, TypeScript `tsc`)
- **Pre-commit**: `uv run pre-commit run --all-files`
- **Deploy to test server**: `dainstall` (configured via `~/.docassemblecli`)

## Core Invariants & Traps
- **Never re-serialize YAML**: Patch exact source ranges; preserve author comments, quotes, key order, and blank lines.
- **PyYAML block sequences**: Ends where next token begins; use `node.value[-1].end_mark` for true end of sequence.
- **AST byte offsets**: Python `ast` column offsets are UTF-8 bytes, not char offsets. Edit against `code.encode("utf-8")`.
- **Computed vs Literal**: Values computed by Python expressions are read-only in UI; never wrap expressions in `repr()`.
- **One name, one home**: Update existing author blocks in place instead of duplicating into Weaver blocks.
- **Front End**: Vanilla JS and Bootstrap (no jQuery). Run `npm run check` and update `test_editor_frontend.py` when modifying UI controls.
