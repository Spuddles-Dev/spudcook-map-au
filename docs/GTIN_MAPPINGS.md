# Product identities and GTIN mappings

The food stream is the public mapping source. Each `content.products` entry in
its snapshot pages retains the retailer listing ID and these existing fields:

| Field | Meaning |
| --- | --- |
| `product_id` | Stable retailer listing key, such as `coles_123456`. |
| `store_code` | `aldi`, `coles`, `drakes`, `iga` or `woolies`. |
| `barcode` | Public barcode string, or null; preserve leading zeroes. |
| `gtin_id` | Linked backend identity, or null; not the barcode itself. |
| `gtin_verified` | Whether the listing receives verified shared GTIN facts. |
| `gtin_revision` | Shared record revision, or null; not a verification flag. |

A known barcode is not the same as a linked identity. A linked identity is not
necessarily verified. Revision numbers do not prove approval. Products without
mappings remain separate listings and can still carry product facts and prices.
Do not merge products by name, copy another pack's barcode, infer a GTIN from a
retailer ID, or treat missing nutrition/allergens as known negatives.

## How future mappings reach clients

1. Scrapers and explicitly collected evidence establish candidate barcodes in
   the backend. Private evidence and drafts stay there.
2. The operator resolves barcode/pack conflicts and explicitly links each listing.
   The combined product/GTIN editor reviews shared facts and verifies the record.
   Shared authority requires the backend's eligible, unblocked identity policy.
3. Backend publication projects eligible facts into `catalogue_products`.
   Dirty revisions trigger materialization of a consistent food release.
4. The hourly host publisher runs authenticated materialization, exports changed
   food metadata and submits a candidate. The public workflow validates it,
   verifies immutable release bytes and advances `distribution/v2/food.json`.
5. Clients install a complete snapshot or its exact-base delta. A mapping edit
   replaces the complete changed product record, including nulls and approval
   withdrawal. Identity-only edits do not invalidate vendor price packages when
   retailer product membership stays the same.

These fields and this publication path exist now. Completing mappings for every
product is future editorial work, not a claim of complete coverage. This public
repository cannot approve GTINs or create backend links.

## Reproducible coverage audit

```bash
python tools/audit_catalogue.py
python tools/audit_catalogue.py --output /path/outside/repo/catalogue-audit.json
```

The audit verifies all six published v2 pointers against local schemas, archive
hashes, page checksums and membership rules before counting. Counts distinguish
barcode coverage, linked identities, verified records and unresolved listings
per retailer. They describe the pinned public release, not unpublished backend
drafts or physical-store stock. Candidate/current differences are reported
separately and never promoted by this read-only command.

Monorepo regression suites cover reviewed GTIN publication and projection.
Public validation checks wire format and integrity; it cannot establish that a
photographed barcode belongs to a product. Retain immutable tags required by
installed clients and bundles. Never update the historical `data/` exports to
simulate a current mapping release.
