# ADR-0010: Windows Openness Worker

## Status

Accepted

## Context

TIA Openness and the existing CLI are Windows-only. ResearchOS otherwise favors a single
Docker Gateway for application APIs and XML/ZIP parsing. Running that Gateway on Windows,
or routing all traffic through a Windows host Gateway whenever a binary TIA project is
uploaded, couples the whole product to a workstation capability and weakens the normal
deployment model.

## Decision

Keep one Docker Gateway as the application boundary. Add a capability-specific local
Windows worker for Openness export:

- the worker exposes `GET /health` and `POST /export`;
- `POST /export` accepts the project as the multipart field `project` and returns a ZIP;
- the default local listener is port `8015`;
- Docker Gateway calls `http://host.docker.internal:8015`;
- Gateway and worker share `RESEARCHOS_OPENNESS_WORKER_TOKEN`;
- XML and ZIP SimaticML ingestion remains in Docker Gateway;
- nginx and the frontend never proxy the worker;
- HostGateway remains as an explicit diagnostic and fallback mode.

## Consequences

Normal Windows deployments retain the Docker data plane while gaining binary project
export. Linux and Openness-free hosts degrade predictably to XML/ZIP ingestion. The
Windows worker has a larger local trust boundary than the stateless Gateway: it can open
local TIA projects and invoke the Openness CLI. Docker requires a non-loopback listener,
so `/export` requires a shared bearer token and operators must restrict port 8015 with a
host firewall to the Docker Desktop / trusted workstation network. Token rotation requires
restarting both worker and Gateway. The export path also carries a multipart upload and
ZIP response across the Docker host boundary.

## Amendment 2026-09: write-back via `POST /import`

The worker now also closes the HITL write-back loop for Docker deployments.
`POST /import` accepts one ZIP (`project/` TIA tree + `import/` staged
XML/SCL) plus `plc_name` / `compile_after` query parameters, runs the shared
`agents.plc.tia.writeback.execute_writeback` logic locally (same Safety/F-block
refusal, same fail-closed compile gate), and returns the JSON report. The
Gateway's write-back confirmation delegates to the worker automatically when
`RESEARCHOS_OPENNESS_WORKER_URL` is configured on a non-Windows host. Security
posture is unchanged (shared bearer token, one serialized lock per Portal
instance, port 8015 firewalled). `.zap` archive after import remains a
HostGateway capability.
