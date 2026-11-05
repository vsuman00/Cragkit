# PostgreSQL embedding profiles

For example, two vectors can both have 1,536 dimensions and still belong to different embedding spaces. A fake vector must never be stored or searched as an OpenAI vector. Cragkit keeps separate tables and checks the full profile descriptor.

The default remains `FAKE_PROFILE`. The additive [PGO-r1 contract](../contracts/POSTGRES_OPENAI_V6.md) permits explicitly selecting the existing `OPENAI_PROFILE` for PostgreSQL ingestion, dense/hybrid retrieval and the PostgreSQL corrective backend. It installs no model on the laptop. The application supplies an embedding transport, the matching tokenizer, disclosure permission and a bounded execution policy. Imports and constructors do not discover keys, contact providers or apply migrations.

## Upgrade explicitly

Start from the existing two-step pgvector setup and the hardened private schema. Use the configured administrative scalar `PG*` environment, an owner-only password file and `PGSSLMODE=verify-full` with the correct CA. See [storage setup](../storage/postgres/README.md) for prerequisites. The operator requires the schema/history owner and refuses an unknown setup history or altered catalog.

```sh
python3 tools/check_postgres_profiles.py --apply --confirm-dedicated-target
python3 tools/check_postgres_profiles.py --check --confirm-dedicated-target
```

The third setup script and its history row commit together under the existing migration lock. A failed transaction rolls both back. The first two setup files, lexical history and active generation stay unchanged. Repeating `--apply` verifies the existing upgrade; `--check` is read-only. This tool does not install pgvector, repair a drifted schema, grant runtime privileges or create access policies.

Deployment owners must explicitly grant `SELECT` on the selected vector table to readers and `SELECT`, `INSERT` and `UPDATE` to writers, with the same trusted tenant/collection RLS policy as the existing data. Required vector functions include the dimension-checking cast `cragkit_vector.vector(cragkit_vector.vector,integer,boolean)` as well as dimensions, norm and cosine distance. Keep registry/setup history read-only for runtime roles. Retain the existing least-privilege restrictions; broad administrator membership cannot replace these grants.

The new table is `cragkit.chunk_vectors_openai_te3small_1536`. Existing fake-only roles can keep using their table after the upgrade. OpenAI selection without the required table permission fails before inference. Missing `UPDATE` is still a writer failure even when `INSERT` is allowed. Permission checks on a comma-separated PostgreSQL privilege string mean *any* listed privilege, so the implementation checks each required privilege separately.

An old binary may reject the three-row setup history. Do not delete its history row or relabel real vectors to make a downgrade pass. Package downgrade and data restore require the separate V6-07 rehearsal.

## Select the trusted profile

Supply the same explicit profile to the adapter and its PostgreSQL consumer:

```python
from cragkit.embeddings import OPENAI_PROFILE
from cragkit.retrieval import PostgresRetriever

# resource and embedder are application-owned, explicitly configured objects.
retriever = PostgresRetriever(
    resource, mode="hybrid", embedder=embedder, embedding_profile=OPENAI_PROFILE
)
```

```javascript
import { OPENAI_PROFILE } from 'cragkit/embeddings';
import { PostgresRetriever } from 'cragkit/postgres';

const retriever = new PostgresRetriever(resource, {
  mode: 'hybrid', embedder, embedding_profile: OPENAI_PROFILE,
});
```

The selected profile is trusted constructor configuration, never an agent-editable request field. Before inference, the library validates storage using a short lease and releases it. It validates again in the actual search/write transaction. Dispatched failures count as calls with unknown usage; predispatch refusal does not count as a call. A reported token count or estimated cost does not prove an account charge.

## Validate without inference

The native mechanics report (retained privately) records the explicit disposable command, pinned PostgreSQL/pgvector prerequisites, rollback, permission and cross-runtime checks. Routine tests use fake embeddings. Native OpenAI dispatch probes deliberately fail before returning vectors. Real embedding publication and live quality are separate claims; the recorded small five-mode comparison and its limitations are summarized in [RC1 notes](releases/V6.md).

Optional exercise: remove `UPDATE` from a disposable writer role and predict whether ingestion reaches the provider. It must fail admission first.
