# domains/novel_digest

Second domain — validates that Loom's abstractions generalize beyond `tiny`.

Pipeline: chapter digest → entity merge → timeline merge (serial across shards)
→ volume summary → consistency check → final report. Mirrors CubeClaw's
GlobalBatch topology structurally; only the node content is domain-specific.

Per §10 of the architecture doc, this is the abstraction-regression test: every
kernel change forced by this domain is logged as a leak and fed back as new SPI.
