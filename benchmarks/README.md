# RiskForge benchmarks

Reproducible performance measurements. Run:

```bash
make bench          # or: python benchmarks/perf.py
```

Timings are wall-clock and indicative, not a guarantee. They show how the cost
scales with the size of the log and the register, not absolute performance.

The numbers below were measured on 2026-10-15 on RiskForge 2.0.0 development code
(the PR 3 branch), on an Apple M5 Pro with macOS 27.0.1 and Python 3.11.17. Each
figure is the median of three runs; the runs differed by less than 3%. The 1.1.3
columns come from the `benchmarks/perf.py` of the `v1.1.3` tag, run on the same
machine, Python and day. That script times the same loops; 1.1.3 has no unit of
work, so its loops run without one.

## Audit append (hash-chained log)

The loop runs inside one `AuditEngine.unit_of_work()`, so the integrity check that
opens a change runs once. Each `record()` then stages one entry and commits it: it
writes the `txn.json` journal, appends and fsyncs the log line, rewrites
`audit.head.json` and removes the journal. Each entry also records the SHA-256
fingerprint of its system's register (ADR-03), which reads and parses
`register.yaml` again.

| entries | total (s) | per entry (ms) | verify chain (s) | 1.1.3 per entry (ms) | 1.1.3 verify chain (s) |
|--------:|----------:|---------------:|-----------------:|---------------------:|-----------------------:|
| 100     | 0.113     | 1.13           | 0.001            | 0.30                 | 0.001                  |
| 500     | 0.556     | 1.11           | 0.003            | 0.30                 | 0.003                  |
| 1000    | 1.138     | 1.14           | 0.007            | 0.33                 | 0.005                  |
| 2000    | 2.341     | 1.17           | 0.018            | 0.38                 | 0.010                  |

Per-entry time is still flat, so building a chain stays O(n), but each entry now
costs about 1.1 ms where 1.1.3 took about 0.3 ms, roughly 3.7 times as much. Under
`cProfile`, about 70% of the time for 1,000 appends went to reading and parsing the
register for its fingerprint and about 24% to the commit. Profiling slows Python
code more than system calls, so treat that split as approximate. Full-chain
`verify` is still a single linear pass: 18 ms at 2,000 entries, where 1.1.3 took
10 ms.

## add_risk (full engine path)

`add_risk` rewrites the register YAML, which serialises every item, and records one
audit entry whose fingerprint parses that register again. Both are O(n) per call, so
adding items one by one is O(n^2) in the register size.

| items | total (s) | per item (ms) | 1.1.3 per item (ms) |
|------:|----------:|--------------:|--------------------:|
| 10    | 0.085     | 8.5           | 4.7                 |
| 50    | 1.571     | 31.4          | 18.3                |
| 100   | 6.053     | 60.5          | 35.6                |
| 200   | 23.859    | 119.3         | 70.4                |

Each call costs about 1.7 times what it did in 1.1.3. This is comfortable at the
sizes a real Article 9 assessment produces (a pattern plus a question bank of 37
items lands in the tens). It only becomes noticeable past about 100 items in one
register. If a future use case needs very large registers, the register store would
move from a whole-file rewrite to an append-structured item log; the audit log
already works that way.

The rows above run every call inside one unit of work. As separate changes, the way
separate CLI commands run, each call also takes the project lock and runs the full
integrity check, which reads the whole log and every register:

| items | total (s) | per item (ms) |
|------:|----------:|--------------:|
| 50    | 2.222     | 44.4          |

That is about 13 ms per call more than the same 50 items in one unit of work. 1.1.3
had no such check, so this row has no 1.1.3 figure.

## Interpreting drift

A regression here shows up as the per-entry or per-item column growing
super-linearly. The audit column should stay flat; if it starts climbing with
size, the tail-chaining path has regressed to a full-chain scan.
