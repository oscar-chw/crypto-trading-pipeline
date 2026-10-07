# Vendored: crypto-desk-blueprint

- Source: https://github.com/oscar-chw/crypto-desk-blueprint
- Commit: 8509898c0ae3487f7e78425b10ea3cb2c736da3c (unmodified; MIT, see LICENSE)
- Files: `pipeline/`, `conformance/`, `LICENSE`, `pyproject.toml` (its pytest markers)

Vendored rather than pinned as a pip git dependency because the published package ships only `pipeline/`
(`[tool.setuptools.packages.find] include = ["pipeline*"]`); the conformance suites this repo runs are
not installable. To update: `git archive <commit> pipeline conformance LICENSE pyproject.toml` from the
blueprint into this directory, change the commit above, and run `scripts/conformance.sh`.
