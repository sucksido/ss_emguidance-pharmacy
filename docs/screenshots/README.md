# UI screenshots

Captured with Playwright (Chromium, 1440×900 at 2× scale; mobile at 390×844) against the seeded dataset.

| # | View | Shows |
|---|---|---|
| 01 | [Medicine search](01-medicine-search.png) | Catalogue, keyset pagination |
| 02 | [Search filtered](02-medicine-search-filtered.png) | Partial name/code match (`zen`) |
| 03 | [Medicine detail](03-medicine-detail-rule-timeline.png) | Rule in force today, rule history timeline, superseded rules |
| 04 | [Introduce rule refused](04-introduce-rule-refused-retroactive.png) | `RETROACTIVE_RULE_CHANGE` mapped to the `effective_from` field |
| 05 | [Dispense capture](05-dispense-capture.png) | Form plus today's limits for the medicine |
| 06 | [Dispense rejected](06-dispense-rejected-all-reasons.png) | Three simultaneous violations, each shown on its field and in the summary |
| 07 | [Dispense accepted](07-dispense-accepted.png) | Recorded dispense pinned to its governing rule |
| 08 | [Patient ledger](08-patient-ledger.png) | Dispenses for one patient, newest first, paginated |
| 09 | [Ledger lookup](09-patient-ledger-lookup.png) | Empty state |
| 10 | [Mobile](10-mobile-dispense-capture.png) | Dispense capture at phone width |
