# Agent-MD public release audit

Audit date: 2026-08-20

## Release identity

This is the public framework repository accompanying **Agent-MD: Selective LLM Intervention with Event-Driven Escalation for Stateful GCMC–MD Campaigns** (https://doi.org/10.48550/arXiv.2608.07637).

The repository was rebuilt from the RC1 public layout. The active development repository was used only to confirm the latest implementation and restore public-safe original files that RC1 omitted.

## 1. Final directory tree

The exact tree is recorded in `release_audit/final_tree.txt`.

## 2. Retained files

The exact list of 96 retained files is recorded in `release_audit/retained_files.txt`.

Key retained content:

- original `mtagent/` package name, all 21 implementation modules, imports, CLI entry points, and workflow logic;
- `AGENTS.md`, RC1 README structure and usage instructions, original public documentation, and source notes;
- all 22 RC1 source-level tests;
- five public campaign case definitions, campaign specification, template directories, schemas, preparation utilities, and validation utilities;
- original root `templates/SPCEH2O_types_8_10.txt` and the campaign-referenced copy;
- one representative replay in its original RC1 canonical path with event, evidence, decision, and decision schema;
- event, evidence-bundle, and reasoning-decision schemas;
- `pyproject.toml`, MIT `LICENSE`, `CITATION.cff`, `.gitignore`, and third-party notices.

## 3. Deleted files

The exact list of 179 RC1 files excluded from final is recorded in `release_audit/deleted_files.txt`.

Excluded classes:

- manuscript, LaTeX, supplementary, PDF, and all `paper/` content;
- figures, figure-source data, table-source data, authoritative paper results, and operational paper summaries;
- plotting and manuscript-figure preparation scripts;
- replay benchmark aggregates, child stdout/stderr, runtime summaries, blocked executable shims, extra cases, and temporary logs;
- RC1-only candidate reports, blockers, old checksum/path maps, and transformation ledgers;
- `.git`, caches, builds, archives, backups, trajectories, dumps, restarts, monitors, and compressed archives.

No source file was deleted or modified; exclusions apply only to the new release copy.

## 4. Differences from RC1

The exact sanitized recursive comparison is recorded in `release_audit/rc1_diff.txt`.

Material differences:

- added `AGENTS.md`, `.gitignore`, MIT `LICENSE`, final citation metadata, and the retained SPC/E templates from the active source;
- minimally amended the RC1 README without changing original test or entry-point instructions;
- added event and evidence schemas alongside the existing decision schema;
- pruned paper-specific and large scientific output while retaining one complete illustrative replay;
- no `mtagent/*.py` implementation file differs from RC1 or the latest development source.

## 5. GitHub public-release assessment

**PASS.** The repository can be used directly as the GitHub public release source for the Agent-MD framework. It contains no Git metadata and no production data. External ClayCode, ClayFF, and production structure assets remain intentionally unbundled and are reported as missing/blocked by the dry-run planner.

## 6. Size

- Files: 96
- Total: 1.2M (948968 bytes)

## 7. Python imports and tests

- Original module/import path: `mtagent` — unchanged.
- Campaign planner: passed using `python -m mtagent.plan_campaign`.
- Full source test suite: **207 passed, 1 skipped**.
- Replay event/evidence/decision schema validation: passed.
- JSON and YAML parsing: passed.

## Public-safety checks

- Personal/HPC absolute paths: zero findings.
- API keys, tokens, passwords, private keys, and credentials: zero findings.
- Personal email addresses: zero findings.
- SPC/E templates: no path, credential, username, or private configuration findings.
- Prohibited manuscript, trajectory, restart, dump, monitor, cache, build, archive, backup, ZIP, and TAR artifacts: zero findings.

No GitHub push was performed.
