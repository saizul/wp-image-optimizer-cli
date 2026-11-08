# Contributing

Thanks for helping improve wp-imgopt. Bug reports, test cases and focused pull requests
are all welcome.

## Setup

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
```

## Before opening a pull request

```bash
ruff check .
ruff format --check .
pytest
```

CI runs the same checks on Python 3.10, 3.11, 3.12 and 3.13.

## Guidelines

- Keep one change per pull request and describe the user-visible effect.
- Add or update tests. Tests build their own images on the fly; please do not commit
  binary fixtures.
- Never let a single bad file abort a bulk run: return an error result instead of raising.
- Anything that writes to disk should write to a temporary file first and move it into place.
- Commands printed by `--sql-replace` must stay shell-safe (quote every argument) and must
  never be executed by the tool itself.
- Update `CHANGELOG.md` under an "Unreleased" heading.

## Reporting bugs

Include your Python and Pillow versions, the exact command, and the part of the output
that shows the problem. Do not attach private images.
