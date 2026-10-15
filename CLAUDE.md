# Repository guidance

This is the public Australian FeedMyBudget data distribution repository. Source
code, scrapers, PostgreSQL and editorial review live in the private
`fmb-monorepo`; this repository contains publication tooling as well as data.

## Current layout

- `distribution/v2/food.json`: published food discovery pointer.
- `distribution/v2/prices/<vendor>.json`: five vendor pointers, each with eight state/territory packages.
- `distribution/catalogue-release.json`: version 1 compatibility pointer.
- `distribution/**/candidate-*.json`: publisher staging inputs.
- `schema/`: generated monorepo contracts, not independently authored DTOs.
- `tools/`: validation, immutable-release publication and audit commands.
- `data/`: historical exports, not current client discovery or current prices.

## Publication rules

PostgreSQL reviewed publications flow through the API's immutable catalogue and
the dedicated host publisher. Run authenticated materialization before export.
Only the public workflow advances pointers after verifying complete immutable
releases. Never edit GTIN facts, pointers or archives by hand, replace tagged
bytes, or force-push. Keep credentials, account data, private photos, review
drafts and correction queues out of this repository.

Product IDs use `woolies_`, `coles_`, `aldi_`, `iga_` and `drakes_` prefixes.
Keep barcodes as strings, preserving leading zeroes. A barcode or `gtin_id`
alone does not establish verified shared identity. Unknown mappings stay unknown.
See [GTIN mappings](docs/GTIN_MAPPINGS.md).

## Validation (Python 3.12)

```bash
python -m pip install -r tools/requirements.txt
python -m unittest discover -s tools/tests -v
python tools/validate_distribution.py
python tools/validate_streams.py
python tools/audit_catalogue.py
```

See [README](README.md) and [publication process](docs/EXPORT_PROCESS.md).
