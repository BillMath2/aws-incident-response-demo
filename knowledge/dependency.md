# Dependency degradation

When checkout errors coincide with an unhealthy payment dependency or upstream timeouts, record the dependency evidence and escalate to its owner. A recent checkout deployment does not prove causation. Do not roll back checkout solely to treat an upstream outage. Collect timestamps, timeout excerpts and dependency health; if dependency health is unknown, request it. Never claim that a dependency recovered without new observations.
