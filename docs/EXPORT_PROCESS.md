# Export Process

This repository is a generated CDN target for FeedMyBudget.

## Command

Run from `fmb-monorepo/backend/scripts`:

```bash
python export_github.py --all --compress --repo /path/to/spudcook-map-au
```

## Output

The exporter writes:

```text
data/
+-- manifest.json
+-- products/{store}.json.gz
+-- reference-prices/{store}.json.gz
+-- specials/{store}.json.gz
```

## Manifest Shape

The active manifest shape is:

```json
{
  "version": "202604180000",
  "lastUpdated": "2026-04-18T15:17:28Z",
  "stores": [
    {
      "storeCode": "woolies",
      "productsFile": {"url": "data/products/woolworths.json.gz"},
      "referencePricesFile": {"url": "data/reference-prices/woolworths.json.gz"},
      "specialsFile": {"url": "data/specials/woolworths.json.gz"}
    }
  ]
}
```

Only data referenced from `stores[]` should be kept in this repo.
