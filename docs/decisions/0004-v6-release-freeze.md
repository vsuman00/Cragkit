# 0004: V6 release and evaluation freeze

This dated decision records the design at acceptance. It does not report current implementation or release completion; use the [current roadmap](../roadmap.md) and [RC1 notes](../releases/V6.md) for that state.

Accepted on 31 October 2026 for the configuration below. This decision does not establish release readiness.

For example, a provider outage cannot improve abstention precision. An invalid source at rank one cannot move a valid rank-two source into rank one. The independent evaluator preserves both distinctions.

The candidate configuration (retained privately) freezes five comparison modes, original approved corpus/label digests, metric definitions, request limits, live-call ceilings and local resource targets before a deliberate held-out run. The metric definitions (retained privately) and coverage inventory (retained privately) have separate owners. Historical evidence is indexed, not relabelled as current verification.

The user chose MIT and asked for a recommendation for their first open-source library. MIT permits reuse and distribution subject to retaining its notice; it does not require downstream source publication. We retain that choice and add the [license](../../LICENSE). [Official MIT terms](https://opensource.org/license/mit) are authoritative. Dependency/provider notices remain their respective licenses and V6-06 audits their distribution requirements.

The intended candidate labels are Python `1.0.0rc1` and npm `1.0.0-rc.1`.
Originally manifests were to remain internal `0.0.0` until V6-06. The
[31 October identity amendment](0005-release-candidate-identity.md) moves version
and native engine-identity preparation to V6-02F, before the first held-out run.
V6-06 still prepares and verifies exact release artifacts through its later
gates. A milestone name is not a registry release. No package name ownership or
registry publication is implied.

Prior V5 observations (retained privately) supply explicit same-machine reference measurements. Import latency ceilings are three times those fresh-process samples; RSS and logical installation ceilings are twice them. These are conservative engineering budgets, not newly measured performance or universal hardware promises. New measurements must disclose cache conditions, sample counts and optional services. Request limits retain the existing 25-second deadline and bounded candidates, attempts, providers and pools.

Quality targets require zero observed source/access/integrity violations, operational failures and false-sufficient results within the declared suite. Paired ranking/support comparisons require no regression for the stated added stages; all five modes and complete denominators must be reported even on failure. Those criteria are motivated by prior development comparisons, without reusing their curated policies as held-out truth. The initial held-out packet was exposed to its original authors/reviewer before sealing, so it cannot support a claim of independently unseen population quality.

Retrieval and planning may receive queries, trusted scope and filters, never reviewed support spans, answerability or facet states. Default coverage remains unknown when no applicable policy is configured. This is a retrieval comparison, not validation of a new semantic assessor or final-answer generation. Query-only corrective variants replace the old answer-derived development oracle. Any result-driven policy change contaminates this held-out revision and requires a fresh reviewed set for a later unbiased comparison.

Live evaluation uses the already selected OpenAI embedding and Cohere reranking profiles. No local model installation is required. A dedicated OpenAI key is being provisioned through secure setup; no live call occurred during preregistration. Total admission is capped at USD 0.02, split into USD 0.01 per provider, concurrency one and zero retries. Verify current official prices, token admission and all mechanical inputs before dispatch. Only the original approved public synthetic corpus/query packet may be disclosed. Private pilot/user documents are excluded. Record actual responses for bounded replay and distinguish logical library calls from actual provider dispatches/billing.

The developer trial compares manual native PostgreSQL retrieval with the installed library on the same corpus and required behavior. Predeclared tasks cover setup/ingestion, authorized retrieval, partial-versus-failure diagnosis and a bounded update/configuration change. Record time, failures, assistance and task success. A missing unfamiliar human participant leaves usability and comparative-effort claims unvalidated; an agent rehearsal cannot become a human trial.

Publication remains a separate V6-08 action after candidate verification. A prepared workflow, passing local tests or a Git push cannot prove a hosted CI run or registry install. The [release guide](../releasing.md) teaches those separate steps. Learning exercise: explain why a failed held-out target cannot be fixed by silently lowering its threshold.
