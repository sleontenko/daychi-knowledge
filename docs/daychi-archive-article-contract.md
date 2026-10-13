# Archive article contract and review

Daychi owns the coexisting provider profile daychi-wiki-archive-articles/1, its source registration, storage and reader. Knowledge owns preparation, editorial validation, independent review and the gated importer. The provider implementation is [Daychi PR #10](https://github.com/sleontenko/daychi/pull/10); [PR #11](https://github.com/sleontenko/daychi/pull/11) preserves the legacy reader format and adds active archive publication metadata. Existing content, semantics and YouTube article v1 remain supported.

The local archive_articles models mirror the provider with local import names. The synthetic fixture covers an archive source, admitted quote, structured article and contextual navigation. Corpus, reading proofs, registry, receipts and credentials remain outside Git.

## Source and evidence authority

A Drive source has an opaque catalog material ID and canonical drive identity. Binary-identical aliases retain original titles, sizes and SHA256; the canonical identity is their lexicographically smallest source ID. Collection/cohort names group the archive and do not verify recording dates. Original PCM duration/hash, both original ASR text hashes, provenance and diagnostic pins remain immutable.

An optional corrected pair records its actual two model identities, full text hashes and distinct provenance/quarantine hashes. Hybrid exports identify original and replacement engines honestly. Reuse of an unchanged clip requires exact raw bytes from both engines; a changed clip requires actual new reading. A forced Russian response and a non-Hebrew comparison model cannot establish Hebrew meaning. Repair preserves original responses and inherited flags.

Each Drive quotation has an exact contiguous valid segment window, PCM times and an explicit admission: source namespace, clip IDs, source and clip warnings, a scoped reason, no unresolved issues and audio_verified=false. Hash equality proves binding, not meaning. Negation, conditions, speaker boundaries and terminology need actual paired-text review. Unsupported or unintelligible passages are omitted, not reconstructed.

Archive articles and Drive-supported pages use text_reviewed_asr_draft. Coverage notes state text-only scope and omissions. Complete machine-text reading is not listening, measured transcription accuracy, completeness of excluded speech or teacher approval. Diagnostic flags remain in private proofs.

## Validation and coordinator workflow

Use a fresh owner inventory and unchanged registry to reserve every source alias and concept. An article assignment carries explicit editorial revisions for every article and page. The original preparation journal and notes-classification lineage are retained.

scripts.wiki_archive_article_validate validates the final private packet: exact source files and raw models, original/corrected provenance, complete attributed reading, evidence windows/diagnostics, every claim/concept/link, exact inline code-point spans and direct article paths. Authors and source reviewers must differ per source. A team proof may reuse earlier reading only with its original actor, fresh bytes, complete coverage and pinned proof chain; normalization cannot claim new reading. Published YouTube source text can be reused through the same attributed checks.

    python -m scripts.wiki_archive_article_validate --root "$WIKI_PRIVATE_PACKET" --review "$WIKI_PRIVATE_REVIEW"
    python -m scripts.wiki_article_import --batch "$WIKI_RESULT"
    python -m scripts.wiki_article_import --batch "$WIKI_RESULT" --apply \
      --password-file "$WIKI_OWNER_PASSWORD_FILE" --workflow-db "$WIKI_WORKFLOW_DB" \
      --assignment "$WIKI_ASSIGNMENT" --receipt "$WIKI_RECEIPT"

The importer selects the archive owner endpoint from modeled format and retains accepted-hash, separate publication authorization, same-origin/CSRF and durable receipt gates. The collaboration protocol still applies. Task-specific owner instructions and any authorized exception must be recorded honestly; never invent human inspection of an unseen hash.

## Coherent page replacement and navigation

An object fingerprint includes its complete bundle envelope. Updating one page may deactivate a prior bundle. Reconcile the full affected closure: retain old articles, canonical pages, claims, evidence and links, with explicit next editorial revisions when the envelope changes. Underlying source/content revisions stay unchanged. Probe the exact old bundles and new closure in a disposable database; a schema stub is a runtime experiment, never editorial approval.

Concept placement comes from paragraph meaning and an exact phrase, not keyword search. Direct related paths need genuine links from both articles through one concept and a concrete explanation of their different contributions. Preserve distinct practices, conditions and metaphors. Do not infer lesson order from a topical connection. The shared reader uses direct article/concept routes, headings, paragraphs, contents and Back.

## Inventory and publication QA

Owner inventory adds archive_source for registered Drive rows. Optional archive_article exposes format, editorial revision and status only for a matching source pin with an active article bundle. A registration, source-only dependency or stale bundle is not published prose. The snapshot counts archive articles separately from summaries and coalesces aliases only through validated binary bindings. Legacy YouTube fields retain their meaning.

After import check all authorized DTOs, source and v1 preservation, replay, anonymous recording protection, actual navigation and registry preservation. Only then mark verified. Recording links open the original Drive file; PCM times are references, not promised seeking or proof of Drive permission. Anonymous projections omit recording IDs/URLs under existing policy.

## Reducing repeated work

Before scaling ASR, test language changes throughout a full recording, including mid-recording changes; choose a comparison engine supporting those languages. Cache immutable responses, repair selected clips, and bind unchanged paired bytes. Assign disjoint recording groups to authors and opposite groups to full-source reviewers. Use lossless bounded reading chunks, restore truncation gaps and record coverage.

Read stable source text once, then review exact changed claim/quote/navigation bytes in that context. Freeze a candidate, retain its old hash and recheck deltas. Runtime, editorial and publication checks have separate evidence; tests cannot replace meaning review. Serialize process launches if host descriptor pressure requires it, retaining completed proof files.
