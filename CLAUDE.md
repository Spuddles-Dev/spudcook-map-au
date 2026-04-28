# CLAUDE.md - spudcook-map-au

This file provides guidance to Claude Code when working with this repository.

## Overview

GitHub data repository for Australian grocery data. Acts as a CDN for the FeedMyBudget Flutter app.

**Primary Purpose:** Store processed JSON data and thumbnails for efficient app distribution.

## This Repo Contains Data Only

This repository contains:
- Processed product data (gzipped JSON)
- Current specials data (gzipped JSON)
- Product thumbnails (JPG images)
- Manifest file for app sync

It does NOT contain:
- Scraper code (see `fmb-backend/scrapers/`)
- API code (see `fmb-backend/api/`)
- Flutter app code (see `FeedMyBudget/`)

## Directory Structure

```
spudcook-map-au/
├── README.md           # Data format documentation
├── CLAUDE.md           # This file
├── docs/
│   ├── PROGRESS.md     # Data pipeline tasks
│   └── EXPORT_PROCESS.md
└── data/
    ├── manifest.json   # Index for app sync
    ├── products/       # Product data by store/category
    │   ├── woolworths/
    │   ├── coles/
    │   └── aldi/
    ├── specials/       # Current specials
    │   ├── woolworths.json.gz
    │   ├── coles.json.gz
    │   └── aldi.json.gz
    └── thumbnails/     # Product images
        ├── woolworths/
        ├── coles/
        └── aldi/
```

## Data Format

All JSON files are gzip compressed.

### Product Format

```json
{
  "id": "woolworths_123456",
  "name": "Product Name",
  "brand": "Brand",
  "category": "pantry",
  "price_cents": 499,
  "unit_price": "4.99/kg",
  "barcode": "9300000000000",
  "size": "500g",
  "image_url": "thumbnails/woolworths/123456.jpg"
}
```

### Special Format

```json
{
  "product_id": "woolworths_123456",
  "current_price_cents": 250,
  "was_price_cents": 499,
  "discount_percent": 50,
  "special_type": "half_price",
  "valid_to": "2026-01-27"
}
```

## How Data Gets Here

Data flows from fmb-backend:

```
fmb-backend scrapers → SQLite DB → export_github.py → This repo
```

See `docs/EXPORT_PROCESS.md` for details.

## Commands

**There are no commands to run in this repo.** All data management happens in fmb-backend.

To update data:

```bash
cd ../fmb-backend/scripts
python export_github.py --all --repo ../spudcook-map-au --push
```

## Access URLs

```
https://raw.githubusercontent.com/Spuddles-Dev/spudcook-map-au/main/data/manifest.json
https://raw.githubusercontent.com/Spuddles-Dev/spudcook-map-au/main/data/products/woolworths/pantry.json.gz
https://raw.githubusercontent.com/Spuddles-Dev/spudcook-map-au/main/data/specials/woolworths.json.gz
```

## Related Repositories

| Repo | Purpose |
|------|---------|
| `fmb-backend` | Scrapers, API, export scripts |
| `FeedMyBudget` | Flutter app that consumes this data |
| `spudcook-map-nz` | NZ data repository (WIP) |
