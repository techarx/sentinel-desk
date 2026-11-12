# ADR-002: Phase 1 platform decisions

- **Status:** Accepted
- **Date:** 2026-11-11
- **Phase:** 1

## Decisions

| Area | Decision | Why |
|---|---|---|
| Container registry | **GitHub Container Registry (GHCR)** | Free, lives next to the code, and GitHub Actions can push with its built-in token (no long-lived registry credentials). |
| Repository visibility | **Public** | Argo CD and kind can pull the repo and images without credentials, and the repo doubles as portfolio evidence. Consequence: no secrets, real data or company details may ever be committed. |
| Entity scope | **Allowlist** in `config/entities.yaml`: only the listed banks, their GLEIF subsidiaries, and fictional Faker-generated counterparties | Nothing outside the list can enter by accident (for example through an open-ended GLEIF query). Services load only allowlisted entities; tests assert every real filing and counterparty traces back to an entry. |
| Bank set | BAC, C, WFC, GS, MS, USB, PNC, TFC, COF, BNY (by SEC CIK) | Ten large US banks with comparable 10-K structure. |
| Data persistence (kind) | `sentinel-data` StorageClass with a fixed path per PVC, backed by `/var/lib/sentinel-data` on the dev machine | Ingested data survives `make down` / `make up`; wiping it is an explicit `make data-reset`. |
| Data placement | Dedicated kind worker labelled `workload: data` | Data stores do not compete with application pods for memory. |

## Consequences

- Public repo: database passwords are generated in-cluster (CloudNativePG creates its own Secrets; others via make targets), never stored in Git.
- The example question from the original plan becomes: *"Compare BAC's and WFC's net interest income over their last three 10-Ks, and flag counterparties in our trade book exposed to both."*
