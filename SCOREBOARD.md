# SCOREBOARD — NM i AI 2026

## Tripletex Handler Status

| Handler | API-kall | Feil | Deterministisk | Testet |
|---------|----------|------|----------------|--------|
| create_employee | 2 | 0 | JA | 23:22 |
| create_customer | 1 | 0 | JA | 23:31 |
| create_product | 1 | 0 | JA | 23:31 |
| create_invoice | 6 | 0 | JA | 23:32 |
| create_project | 2 | 0 | JA | 23:34 |
| create_department | 1 | 0 | JA | 23:33 |
| create_order | - | - | JA (utestet) | - |
| create_travel_expense | - | - | JA (utestet) | - |
| delete_entity | - | - | JA (utestet) | - |
| unknown (LLM fallback) | varierer | varierer | N/A | 23:20 |

**Kjente Tripletex API-krav (lært fra sandbox):**
- Employee: Krever `userType: "STANDARD"` + `department.id`
- Project: Krever `projectManager.id` + `startDate`
- Invoice: Krever bankkontonr på konto 1920 (settes automatisk)

## Submissions

| Tid | Oppgave | Endring | Score | Neste |
|-----|---------|---------|-------|-------|
| Fre 23:15 | Astar Island | Runde 10, 5/5 seeds, prior-basert (0 queries) | Venter | Fikse temporal learning |
| - | Tripletex | Deploy pågår | - | Submit URL |
| - | NorgesGruppen | Trening starter | - | Submit modell |

## Tidslinje

- 22:50 — Prosjekt initialisert, GitHub repo opprettet
- 23:00 — Alle credentials verifisert (Tripletex sandbox + Astar JWT)
- 23:15 — Astar Island runde 10 submittet (5/5 seeds)
- 23:20 — Tripletex create_employee første test (fallback, 60% feilrate)
- 23:22 — create_employee fikset (department + userType), 0% feilrate
- 23:32 — create_invoice testet, full flyt med bankkonto-fix, 0% feilrate
- 23:34 — create_project fikset (startDate + projectManager), 0% feilrate
- 23:37 — Deploy startet (Data-API) + YOLO-trening startet (kit-gpu-server)
