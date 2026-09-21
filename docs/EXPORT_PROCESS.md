# Export and publication

Use the committed FeedMyBudget monorepo exporter with Python 3.12:

```bash
python backend/scripts/export_catalogue_distribution.py --api-base-url http://100.88.216.109:8000 --output-dir ../spudcook-map-au/distribution --minimum-app-build 229
```

This reads immutable public API v2 metadata and prepares explicit chain price
packages for ACT, NSW, NT, QLD, SA, TAS, VIC and WA, for Aldi, Coles, Drakes, IGA
and Woolworths. The API's canonical price resolver supplies complete known and
missing outcomes. No account API or review approval is used. A previous index
must live beside its verified ZIP assets when supplied with `--previous-index`.
An existing candidate is reused automatically for repeat exports.

The exporter validates source contracts, generates deterministic ZIPs and writes
`distribution/candidate-release.json` last. It does not write the current public
pointer or publish anything. Identical semantic data reuses the candidate;
random API price IDs and generation timestamps do not create new data revisions.
Canonical metadata identities and real observation/provenance timestamps remain
unchanged. Price IDs hash context, product count and all page checksums.

Metadata deltas contain full changed records, deleted identities and complete
replacement reference collections. A price patch contains only target pages
whose checksums are absent from its exact base package. The client reuses saved
pages by checksum, rewrites only their release/page envelope and validates the
complete target. Truncated pages and missing outcomes come from the full target
manifest. No useful patch means a complete package, not an empty ambiguous patch.

## Review and publication order

1. Review the candidate and validation summary. Commit the candidate, its ZIPs
   and generated schema changes; do not stage unrelated files.
2. The public workflow validates the checked commit with generated JSON schemas,
   archive budgets, semantic checksums and complete outcome membership.
3. It creates the content-addressed tag at that commit, creates a draft release,
   uploads every archive and the `catalogue-release.json` attachment, and verifies
   GitHub's reported SHA256 digests and sizes. Conflicting assets fail and are
   never overwritten.
4. It publishes and verifies the complete release, then advances the main
   `distribution/catalogue-release.json` pointer. It reads main's exact commit,
   verifies the candidate at that immutable commit, and creates a pointer-only
   commit with that verified parent. The branch update never forces: if main
   advances during publication, the non-fast-forward update is rejected and
   the pointer is left alone. A later run verifies the new head again. If main
   already has a different candidate, the older run also leaves the pointer alone.

Enable GitHub release immutability before first publication. Publication jobs
are serialized and use the repository GITHUB_TOKEN with contents-write permission;
validation and pull-request jobs have read permission only. No database or API
credentials belong here. Monorepo Actions settings are independent and unchanged.

Interrupted uploads remain drafts and are resumable. A published release with
identical assets is idempotent. Failure before the last step leaves clients on
the prior complete release. Tags and assets are never force-replaced. Keep tags
required by bundled app versions; a missing delta base selects the full snapshot.
An interrupted run's orphan tag may point to an earlier source commit: it is
reused only if the tagged candidate and every referenced archive exactly match
the locally validated bytes. Different bytes fail before creating a release.
Old assets may be removed from a later main commit only after their immutable
tags are retained and current-candidate validation still passes.

## Validation tools

```bash
python -m pip install -r tools/requirements.txt
python -m unittest discover -s tools/tests -v
python tools/validate_distribution.py
```

`schema/catalogue-distribution-v1.json` is generated from the monorepo Pydantic
distribution, catalogue-page and price-page contracts. `tools/catalogue_integrity.py`
is an exact copy of the shared checksum implementation. Regenerate both when
those contracts change; do not maintain independent wire DTOs here.
