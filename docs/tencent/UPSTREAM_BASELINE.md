# Pinned GBrain Upstream Baseline

Last updated: 2026-09-24

## Attribution and immutable pin

This repository is a full derived copy of [GBrain](https://github.com/garrytan/gbrain), licensed under the upstream [MIT license](../../LICENSE). Its [Company Brain tutorial](https://github.com/garrytan/gbrain/blob/master/docs/tutorials/company-brain.md) is background for the existing knowledge substrate, not a freshness or permission contract. The integrated release is `v0.54.1.0`, exact commit `6040075c6cb95be5881cc2e1b76ef7d71f4e5d29`, integrated on 2026-09-24 in merge commit `051714a1df41a357a5f0dd1decf42469797d4e16`.

This pin remains fixed for the current evaluation corpus and baseline. An upstream change can alter indexing, source behavior, test results, or fixture interpretation; letting a baseline float would make a comparison unreproducible. Cite the exact upstream commit in every baseline record and review any future upgrade as a separate change.

## Inherited capabilities

GBrain already supplies source-scoped pages, chunks, embeddings, and retrieval; source identity and per-source locks; resumable synchronization and status surfaces; PGLite and Postgres engines with parity requirements; a generated CLI and MCP surface; the operation registry in `src/core/operations.ts`; and BrainBench's hermetic fixture loader, sealed gold, corpus hash, and protected-baseline comparison conventions. These capabilities are retained rather than reimplemented by the freshness extension.

Source identity is part of page identity: `(source_id, slug)` distinguishes pages, and freshness objects must also bind a connector source and external object ID. Existing source locks and status remain upstream authority for current sync behavior; future freshness checkpoints and runs add provider-specific evidence without silently changing that authority.

## Extension points and current gap

Future operations belong in `src/core/operations.ts` and its `src/core/ops/` modules, with CLI and MCP definitions derived from the registry. Engine methods and SQL must remain in PGLite/Postgres parity; schema changes belong in `src/core/migrate.ts` and the engine bootstrap surfaces. Connector source identity must use the existing source model. Freshness eval loaders should follow `src/eval/brainbench/fixtures.ts` and `evals/brainbench/` for strict fixture/gold separation, deterministic hashes, and held-out fixtures.

At this pin, GBrain does not provide one shared provider event ledger, a common provider cursor contract, per-object freshness state, tombstone proof tied to searchability, query-time provider verification, or a versioned freshness receipt. Existing sync behavior must not be described as satisfying those future guarantees.

## Reviewed upstream update procedure

1. Fetch `upstream` tags and commits; verify the proposed tag resolves to an exact commit and retain the current pin in the review record.
2. Review the upstream changelog and the diff from `6040075c6cb95be5881cc2e1b76ef7d71f4e5d29`, especially operations, source identity, engines, migrations, sync, and eval loaders.
3. Merge the exact reviewed commit while retaining both histories and the MIT license. Resolve conflicts against GBrain invariants and this extension's contracts.
4. Regenerate any generated documentation and inventories using the repository scripts, including `bun run build:llms` if upstream reference docs changed and `bun scripts/classify-tests.ts` when tests changed.
5. Run the upstream verification gates plus the Tencent freshness structural, corpus, and behavioral gates applicable at that phase. Rebuild and review baselines against the new pin; never auto-approve a changed baseline from the same branch.

For published documentation links in this derived repository, regenerate from `https://raw.githubusercontent.com/pavan2184/tencent-hack/main` instead of the upstream raw base. The current phase only documents this procedure; it does not advance the pin.
