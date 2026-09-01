# Noemosyne

> Persistent epistemic memory for AI: claims, evidence, uncertainty, disagreement, and belief change—with provenance intact.

Noemosyne is an open-source, self-hostable system for representing not merely what sources say, but **what there is reason to believe, why, under which conditions, and how that view changed**.

It is **AI-first and human-accessible**. The primary product is a structured epistemic engine and machine interface. The web application is a window into the same state—not the system's center of gravity.

## The problem

Search and ordinary RAG retrieve documents or chunks. They do not reliably preserve proposition identity, scope, evidence dependence, disagreement, historical belief states, or the difference between an observation and an interpretation. A fluent synthesis can therefore hide where it came from and erase uncertainty.

Noemosyne makes those distinctions explicit:

- sources remain separate from the claims attributed to them;
- observations remain separate from interpretations;
- evidence only supports or challenges a claim in a recorded context;
- competing claims coexist;
- assessments are reasoned, versioned judgments, not magic confidence scores;
- agents propose changes, but cannot silently rewrite canonical knowledge;
- historical queries use only information available at the requested time;
- predictions have resolution rules and become calibration evidence.

## The smallest useful product

Milestone 1 is a **curated AI-research claim ledger**, not an autonomous world model. It supports:

1. registering source metadata and immutable source fragments;
2. creating context-qualified claims;
3. attaching supporting or challenging evidence with provenance;
4. representing typed relationships and evidence dependence;
5. accepting changes through a proposal and review workflow;
6. publishing immutable epistemic assessments and revision history;
7. retrieving compact, structured `EpistemicContextBundle` objects through REST and MCP;
8. comparing AI answers with Noemosyne against search/RAG baselines.

The MVP succeeds only if the structured context improves citation correctness, contradiction handling, temporal fidelity, or calibrated abstention on a fixed evaluation set.

## Repository shape proposed for implementation

```text
apps/
  api/          FastAPI HTTP service
  worker/       ingestion and evaluation jobs
  web/          Next.js human interface
  mcp/          thin MCP adapter
packages/
  domain/       pure epistemic rules and types
  db/           SQLAlchemy mappings and migrations
  ingestion/    source adapters and extraction pipeline
  retrieval/    lexical, semantic, and graph retrieval
  evals/        fixtures, graders, and experiment runner
examples/
  ai-research/  redistributable seed dataset
```

## Read this package

Start with:

- [`00_EXECUTIVE_OVERVIEW.md`](00_EXECUTIVE_OVERVIEW.md)
- [`03_EPISTEMIC_MODEL.md`](03_EPISTEMIC_MODEL.md)
- [`10_MVP_SPECIFICATION.md`](10_MVP_SPECIFICATION.md)
- [`14_CODEX_IMPLEMENTATION_BRIEF.md`](14_CODEX_IMPLEMENTATION_BRIEF.md)

The numbered documents are normative in ascending specificity. If they conflict, the epistemic invariants in `03`, the MVP boundaries in `10`, and the implementation acceptance criteria in `14` take precedence.

## Status

This package is the product-definition and architecture baseline. Application code intentionally has not started.

## License recommendation

Use Apache-2.0 for software and CC BY 4.0 for original documentation and curated example annotations. Third-party metadata, text, and excerpts retain their own licenses; Noemosyne stores license and access metadata per source and must not redistribute content merely because it can retrieve it.

