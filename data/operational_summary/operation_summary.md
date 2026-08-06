# Operation Summary

Primary campaign: 5 systems x 3 RH states = 15 strict-passing scientific states.

## Core Metrics

| Metric | Value |
|---|---:|
| Deterministic operations | 414 |
| Routine deterministic operations | 410 |
| Deterministic exception-handling operations | 4 |
| Simulation cycles | 120 |
| Analyzer/decision cycles | 120 |
| Continue-current-RH decisions | 105 |
| Strict pass decisions | 15 |
| Archive operations | 15 |
| RH transitions | 10 |
| Provenance checks | 25 |
| Total RH-local MD/GCMC steps | 219,600,000 |
| Real runtime reasoning boundaries | 1 |
| Real production Codex calls | 0 |
| Runtime LLM fraction | 0.000000 |

## Computational Effort by RH

| RH | States | Segments | RH-local steps |
|---:|---:|---:|---:|
| 0.90 | 5 | 52 | 81,600,000 |
| 0.30 | 5 | 53 | 108,000,000 |
| 0.10 | 5 | 15 | 30,000,000 |

## Computational Effort by System

| System | States | Segments | RH-local steps |
|---|---:|---:|---:|
| Mt_Ca_LC040_N8 | 3 | 19 | 34,200,000 |
| Mt_K_LC040_N16 | 3 | 37 | 68,100,000 |
| Mt_Na_LC030_N12 | 3 | 19 | 33,100,000 |
| Mt_Na_LC040_N16 | 3 | 21 | 40,100,000 |
| Mt_Na_LC050_N20 | 3 | 24 | 44,100,000 |

## Interpretation Boundary

The production runtime did not call Codex non-interactively. The K RH0.3 incident is counted as one real reasoning boundary because it required a human-directed semantic audit of step accounting. That audit is evidence for sparse reasoning support, but it is not an autonomous runtime LLM call.
