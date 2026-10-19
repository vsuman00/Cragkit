Agentic Retrieval Pipeline explorer: execution and source review

Reviewed on 19 October 2026. Input: `interactive_visual_im_d2b565f3406507ed.html`. The supplied HTML was preserved. This report supplements `PROJECT_REVIEW.md` with findings from the newly supplied explorer.

The explorer communicates the intended happy path and recovery path clearly through a shared diagram and step inspector. Its JavaScript supports stepping, scenario selection, playback, and node selection. It is a scripted architecture walkthrough: it does not implement retrieval, grading, rewriting, or compression.

What was actually executed

The browser tool rejected opening the local file because its URL policy disallows the `file://` protocol. No alternate browser surface or local web server was used to work around that restriction.

Instead, all three inline scripts were executed in Node's `vm` with a small modeled DOM and controlled timers. This runs the supplied JavaScript and observes its changes to inspector fields, button states, active-node attributes, and edge attributes. It does not run a browser layout engine or establish visual correctness. Google Fonts were not loaded. Playback ticks were advanced deterministically rather than waiting for wall-clock intervals.

The dependency-free harness is `analysis/explorer-analysis.cjs`; the machine-readable results are `analysis/explorer-analysis-results.json`. From the project directory, run:

```sh
node analysis/explorer-analysis.cjs
```

The result is 14 passing checks and 5 failing checks. The command intentionally exits with status 1 while those findings remain. The tests include consistency and accessibility checks, so this is not a count of five JavaScript crashes. The token arithmetic checks assume that the displayed preceding budget is the running balance; the absence of a documented budget definition is itself part of the finding.

| Area | Observed result in the local model |
| --- | --- |
| Script startup | All three inline scripts execute. |
| Initial inspector | Query, token budget, title, step count, and navigation state populate. |
| Happy-path walkthrough | All five steps update payloads, active nodes, and incoming edges. |
| Previous/next boundaries | Navigation remains within the scenario. |
| Scenario switching | Step position, selected scenario, and mode reset correctly. |
| Recovery walkthrough | All eight scripted steps execute, including the recovery edge markers. |
| Ordinary node selection | The corresponding inspector step is selected. |
| Recovery-only node in happy path | It leaves the current step unchanged. |
| Playback | Advances, pauses, stops at completion, and restarts from the beginning. |
| Playback cancellation | Changing the scenario or selecting a node clears the interval. |
| Theme and resize hooks | A valid theme message updates the attribute; a resize notification is emitted. |
| Navigation test sensitivity | A deliberately broken Next handler is detected using an in-memory source mutation. |

The last check does not edit the supplied HTML. No dependencies were installed, no retrieval provider was called, and no application deployment was created.

What this adds to the architecture discussion

The `SCENARIOS` array contains the entire execution story. The happy path has five entries; recovery has eight. `nextStep()` increments an array index, and `updateViz()` copies the chosen entry into the inspector. It does not calculate a branch from a score.

To verify that distinction, the harness changed the happy-path grader's `output.max_score` from 0.88 to 0.10 in memory. The next step remained `ContextCompressor`. This is valid for a storyboard but does not demonstrate that a real correction loop works.

The latency labels, candidate counts, confidence figures, scores, citations, and token counts are supplied constants. Adding the latency labels yields 375 ms for the happy path and 680 ms for recovery. Those sums describe illustrative data; they are not measured retrieval latency. The engine has no benchmark results here.

The explorer also supplies citation strings without fetching source documents or returning actual evidence excerpts. It therefore does not verify citation integrity, relevance, or compression quality. The earlier architecture review's concerns about evidence coverage and source revision tracking still apply.

Concrete findings

1. Repeated nodes select the first attempt. In `selectNode()`, `findIndex()` finds the first matching node ID. On the second `HybridSearchRRF` visit, clicking that node changes the current step from index 5 to index 2. The same selection rule affects the repeated grader. The inspector can therefore show the failed first pass while a reader is exploring the successful second pass. Give execution steps unique identities and separate node identity from attempt identity. A node click can preserve the active occurrence or offer an explicit attempt selector.

2. The happy-path token balance does not reconcile. The preceding displayed budget is 1,850 tokens and the final output reports 620 tokens. Their difference is 1,230, while the inspector displays 1,240 remaining. Using the original 2,000-token output ceiling would produce a different balance again. Define whether this is an output allowance or a cumulative internal model allowance, then derive the display from one source of truth.

3. The recovery token balance also does not reconcile. The preceding balance is 1,700 and the final output reports 710, which leaves 990 under the running-budget interpretation. The inspector displays 1,150. The earlier decreases from 2,000 to 1,850 and 1,700 have no usage ledger. Internal model consumption and final evidence size need separate fields.

4. Markdown fences remain inside the HTML file. Line 1 contains the opening Markdown fence and line 1591 contains the closing fence. They are export artifacts, not part of an HTML document. Remove them in a future corrected copy. This was confirmed from source; their rendered appearance was not browser-verified.

5. Direct diagram interaction lacks keyboard support. The six clickable SVG groups have mouse handlers but no focusability or keyboard activation handlers. The ordinary navigation buttons provide another route through the steps, but direct node selection should also be usable from the keyboard. Use accessible controls or focusable groups with appropriate semantics and Enter/Space handling, then verify focus and announcements in a browser.

Architectural weaknesses illustrated by the scenarios

The recovery description says that it drops strict filters and returns `relaxed_filters: true`. This is only supplied example data, so no real permission bypass occurred. However, it represents an unsafe policy if implemented literally. Separate immutable authorization scope and caller requirements from relaxable inferred hints. Show which hint changed, while recording that access scope stayed fixed.

The decision rule accepts a maximum score above 0.72. It neither checks whether every part of the question has evidence nor rechecks coverage after compression. Add a partial-evidence scenario where one facet has strong passages and the other remains unsupported. The final payload should communicate the missing facet instead of displaying unconditional success.

The query starts as "Why does auth fail on refresh?", then becomes a JWT-expiration question. JWTs and expiration are plausible hypotheses, but the original query did not establish them. An implementation should preserve the original question and identifiers, record inferred assumptions, and avoid letting a speculative rewrite erase the user's intent.

The displayed RRF values, such as 0.89, have no accompanying rank lists, smoothing constant, weighting, or normalization definition. They cannot be checked against a fusion calculation. Label them as illustrative; a later execution trace should expose the method and parameters. Do not present a fusion score as a confidence probability.

The token-savings percentages have no stated uncompressed baseline. Return input evidence tokens, packed evidence tokens, tokenizer identity, and the calculation. A positive reduction percentage is less ambiguous than a negative value labelled savings. Decomposition and correction confidence numbers likewise need a defined measurement method or an explicit illustrative label.

Only successful endings are represented. A useful architecture explorer should also cover exhausted recovery, partial evidence, no authorized matches, provider failure, timeout/cancellation, an undersized context budget, conflicting source versions, and rejection of a forbidden filter change. These are proposed additions, not implemented scenarios.

Browser and integration concerns that remain unverified

The CSS sets `overflow-y: hidden` on both the page and body. The script asks a parent frame to resize via `widget-resize`; this file does not contain that parent's implementation. This may be appropriate inside the original host, but a standalone window shorter than the content risks an inaccessible inspector. That is a source-based risk requiring an actual viewport test, not a reproduced browser finding.

The SVG uses a 660-by-360 coordinate system and scales with available width. Its 12-14-unit text will shrink substantially on narrow displays. A mobile layout should be checked for readable labels and usable hit targets. The source also imports Google Fonts, so offline rendering would use fallback fonts. Neither typography, contrast, clipping, responsive layout, nor assistive-technology behavior was visually verified in this run.

The theme message hooks accept messages without checking their origin or parent identity, and one handler accepts a theme value without validating it against the two supported values. In this supplied code, that changes theme state rather than running arbitrary commands. For a hosted embed, validate the sender and allowed values, and coordinate any restriction with the actual embedding host.

The model tests verify the current DOM interactions but cannot establish real browser event behavior, CSS transitions, observer scheduling, font metrics, or layout. No screenshot or browser-performance claim is supported by this run.

Recommended use of this artifact

Keep the explorer as explanatory documentation with an explicit simulated-data label. Correct the attempt-selection behavior, derive displayed metrics consistently, remove the export fences, and improve keyboard support. Add unsuccessful and partial outcomes before treating it as an architecture acceptance checklist.

Once a retrieval engine exists, let it emit versioned execution events containing a step ID, node ID, attempt, elapsed time, usage, candidate references, estimated coverage, and outcome reasons. The explorer can then replay recorded traces through the same interface used by its simulated examples. Separate fixtures from live measurements visibly.

That would give this work a useful role in Cragkit: developers could inspect why a retrieval attempt changed and which evidence survived packing. The current HTML demonstrates the intended story; the next step is to make that story faithful to the contract and eventually to actual engine events.
