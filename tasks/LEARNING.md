# Learning alongside Cragkit

This guide supports [the master plan](plan.md). Task completion lives in [todo.md](todo.md); understanding can remain pending after a task is technically complete.

| Milestone | What you should be able to explain | Small exercise |
| --- | --- | --- |
| V0 | Package vs application, Python vs Node runtime, types vs runtime validation | Reject one malformed request in both languages. |
| V1 | UTF-8 spans, SQL parameters, transactions, pools, scope and citations | Change a source revision and explain why its old citation must not silently change. |
| V2 | Embeddings, vector dimensions, lexical matching, ranks and RRF | Compute a three-document fusion result by hand. |
| V3 | Relevance vs sufficiency, tokenizer identity and extractive packing | Make a two-facet question become partial by removing one evidence span. |
| V4 | State machines, bounded retries, deadlines and accounting | Stop a repeated rewrite without changing authorization. |
| V5 | Adapter contracts, distributed publication and transport identity | Explain what happens when source publication succeeds but vector publication fails. |
| V6 | Benchmark splits, regression evidence, package artifacts and migrations | Install your own built package in a clean environment and reproduce one published example. |

For each task, ask the assistant to explain one concept before changing code and show a small diff afterward. You can implement a small part yourself, ask for hints, or watch a complete example and then change a test input. Avoid large unexplained code dumps. Prefer one new concept at a time.

Use this note template in a learning journal when useful:

```text
Task ID:
What I expected:
What I observed:
Concept in my own words:
One test or example I changed:
What I can now explain:
What is still unclear:
Next small action:
Learning state: pending / practiced / demonstrated
```

Read papers when their concepts become relevant: technical debt at V0, RRF and BEIR at V2, RAGTruth and ALCE at V3, and CRAG at V4. The [paper index](../papers/README.md) links to the saved PDFs. Read the problem, method and limitations first; reproducing an entire paper is not required to implement this library.

At the end of each version, give a five-minute walkthrough: the developer problem, the API call, the path through the code, one failure case, and the evidence that it works. If a concept remains confusing, use a smaller fixture next session. Learning is part of the work, not a reason to rush into additional architecture.
