# Nexoria Internal Onboarding Guide — Confidential

## About Nexoria

Nexoria is a fictional mid-sized logistics software company founded in 2019 by
Elara Voss and Tomáš Beneš in Brno, Czech Republic. The company builds route
optimisation software for last-mile delivery fleets under the brand name **FleetOS**.

This document is the internal onboarding reference for new engineering hires.
It contains proprietary processes, internal tooling names, and team structures
that are specific to Nexoria and not publicly available.

---

## The Zephyr Onboarding Protocol

All new engineers at Nexoria follow the **Zephyr Protocol** — a structured
30-day onboarding sequence designed by Elara Voss in 2021.

The protocol has four phases:

| Phase | Duration | Name | Goal |
|---|---|---|---|
| 1 | Days 1–5 | Anchor | Set up environment, meet team |
| 2 | Days 6–12 | Dive | Read codebase, shadow senior engineers |
| 3 | Days 13–22 | Build | First solo ticket, code review cycle |
| 4 | Days 23–30 | Fly | Full autonomy, retrospective with Elara |

---

## Internal Tools Specific to Nexoria

### RouteForge
RouteForge is Nexoria's internal route simulation tool. It is NOT open-source
and is not related to any public routing library. Engineers use RouteForge to
test FleetOS optimisation algorithms against synthetic delivery grids.

RouteForge uses a proprietary grid format called **NXG** (Nexoria Exchange Grid).
NXG files have the `.nxg` extension and are defined by the internal spec
written by Tomáš Beneš in 2022.

### DepotDB
DepotDB is Nexoria's internal database layer built on top of PostgreSQL.
It implements a custom ORM called **Parcela** that maps delivery depot entities.
Parcela uses decorator-based schema definition:

```python
@depot(zone="EU-CZ")
class DepotEntity:
    depot_id: str
    capacity: int
    voss_index: float   # proprietary load metric invented by Elara Voss
```

The `voss_index` is a float between 0.0 and 1.0 representing depot load
efficiency. A `voss_index` above 0.85 triggers automatic load-balancing.

### The Canopy Dashboard
The Canopy Dashboard is Nexoria's internal monitoring interface. It runs on
port 9331 by default and shows real-time FleetOS metrics. Access requires
membership in the `nexoria-eng` LDAP group.

---

## Engineering Rituals

### The Tuesday Sync
Every Tuesday at 10:00 CET, all engineers attend the **Tuesday Sync** led by
the current **Sync Captain**. The Sync Captain role rotates weekly in
alphabetical order by first name. New hires become eligible for Sync Captain
after completing Phase 3 of the Zephyr Protocol.

### Voss Review
A **Voss Review** is Nexoria's term for a mandatory architecture review
triggered when a PR changes more than 400 lines across core FleetOS modules.
Elara Voss personally reviews all Voss Reviews unless she delegates to a
**Proxy Voss**, which she has only done twice in company history.

---

## Key Contacts

| Name | Role | Responsible for |
|---|---|---|
| Elara Voss | CEO / Chief Architect | Voss Reviews, Phase 4 retrospectives |
| Tomáš Beneš | CTO | RouteForge, NXG spec, DepotDB |
| Yuki Nara | Head of Onboarding | Zephyr Protocol coordination |
| Priya Mehta | Senior Engineer | Code review, Phase 3 mentoring |

---

## Glossary

- **FleetOS**: Nexoria's main product — route optimisation software
- **RouteForge**: Internal simulation tool, proprietary
- **NXG**: Nexoria Exchange Grid file format (.nxg)
- **DepotDB / Parcela**: Internal ORM for depot entities
- **voss_index**: Proprietary load metric (0.0–1.0, threshold 0.85)
- **Zephyr Protocol**: 30-day structured onboarding sequence
- **Canopy Dashboard**: Internal monitoring UI (port 9331)
- **Tuesday Sync**: Weekly all-engineer meeting, rotating Sync Captain
- **Voss Review**: Mandatory architecture review for large PRs (>400 lines)
- **Proxy Voss**: Elara's delegate for Voss Reviews (rare)
