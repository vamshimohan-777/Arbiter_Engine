# Arbiter Synthetic Policy Reasoning Corpus v1.0

This is a fully synthetic, deterministic corpus for the Arbiter project.

## Contents
- policies: versioned policies with scope, exceptions, supersession and remediation clauses
- precedents: historical rulings with structured context and citations
- queries: benchmark questions covering resolution, manipulation, sensitivity, precedent, point-in-time and simulation
- contrastive_cases: near-identical cases where one decision-critical fact changes
- conflict_pairs: policy pairs for corpus scanning/conflict detection

## Important
These records are fictional. They are suitable for engineering/testing/benchmarking only.
Do not represent them as real company, legal, regulatory, medical or governmental policies.

## Recommended use
Keep `queries.jsonl.gz` as benchmark data. Do not expose `expected_decision` or `gold_citations` to the model during evaluation.
Use policy metadata for deterministic filtering and the policy body for reasoning.
