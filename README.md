# Australian Grocery Data

Compressed export data for the FeedMyBudget app.

## Current Layout

```text
data/
+-- manifest.json
+-- products/
¦   +-- woolworths.json.gz
¦   +-- coles.json.gz
¦   +-- aldi.json.gz
+-- reference-prices/
¦   +-- woolworths.json.gz
¦   +-- coles.json.gz
¦   +-- aldi.json.gz
+-- specials/
    +-- woolworths.json.gz
    +-- coles.json.gz
```

## Source of Truth

This repo is a generated export target. Files are written from the FeedMyBudget monorepo via `backend/scripts/export_github.py`.

## Manifest

`data/manifest.json` is the entry point the app reads for CDN sync metadata. The app uses the `stores[]` entries and their `productsFile`, `referencePricesFile`, and `specialsFile` URLs.

## Notes

- Product and reference-price files are gzip-compressed JSON arrays.
- `reference-prices/` contains seeded state-base prices for initial local app pricing.
- Only files referenced by `data/manifest.json` are considered active.
