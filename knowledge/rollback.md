# Checkout release rollback

Scope: checkout-api sandbox only. A rollback proposal may target release-41 only when the current release is release-42, recent complete observations show elevated errors, dependencies are healthy, and logs corroborate a defect introduced by that deployment. Temporal correlation alone is insufficient. Read health, recent changes and logs. Health and relevant error observations must be no older than five minutes at investigation time. Changes can be collected over a bounded 120-minute window. If evidence is absent, contradictory, stale or dependencies are degraded, escalate for more evidence.

The investigator proposes; an independently authorized human approves the exact proposal hash before its expiry. Only the executor can conditionally update sandbox state. No shell command or real deployment is permitted. A receipt means a synthetic state transition, not recovery; obtain a separate subsequent health observation.
