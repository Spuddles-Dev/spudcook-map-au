# Australian grocery distribution

Public, versioned Feed My Budget catalogue and state/chain price packages. These
files contain shared published data only, never account records or private
nutrition corrections. The backend remains the source of truth.

The April `data/` files are historical exports and are not current prices. New
clients use the version 1 distribution described below.

## Current release and immutable files

The current pointer is `distribution/catalogue-release.json` on `main`. It is
created or advanced **only after** its GitHub Release is completely uploaded,
verified and published. Until the first publication this pointer does not exist.

Each index names a `data-v1-<64-character-content-hash>` release tag. Download
archives using that immutable tag, never from a moving branch:

```
https://raw.githubusercontent.com/Spuddles-Dev/spudcook-map-au/<release_tag>/distribution/<archive.path>
```

The same ZIP bytes are attached to the GitHub Release for native download tools.
Browser clients use the tagged raw URL because GitHub's release-asset redirect
does not consistently provide CORS headers. Public downloads require no token.

Each ZIP contains only `page-00000.json` style members, using the existing typed
API v2 page contracts. The index records compressed and expanded byte budgets,
archive SHA256, page checksums, target identities and exact delta bases. Metadata
includes products, recipes, categories, ingredient discovery, measurement profiles
and published food facts. Prices are separate packages for each Australian state
and chain; national (`ALL`) fallback provenance is preserved. Physical-store
prices are not represented as chain prices.

Bundled app baselines use these exact index and archive formats. An app stages
and validates a complete generation before activation, reuses only a matching
delta base, and otherwise installs the complete snapshot. Observed dates and
missing-price outcomes remain explicit; packaging never makes old data fresh.

## Publishing

See [the export and publication process](docs/EXPORT_PROCESS.md). The only moving
public document is the current pointer. `candidate-release.json` is an operator
staging input, not client discovery. Binary assets live in this repository so
tagged raw downloads work in browsers; GitHub Releases carry the same bytes.

The public workflow runs schema, ZIP, checksum, membership and publication-order
tests without backend credentials. Pull requests can validate but cannot publish.
Source notices and attribution within exported panels must be retained.
