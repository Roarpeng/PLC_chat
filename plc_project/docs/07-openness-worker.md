# Windows TIA Openness Worker

## Topology

ResearchOS keeps one Docker Gateway as the application API. TIA Portal Openness is a
Windows-only capability, so it runs as a local worker process instead of making the whole
Gateway Windows-only.

```text
Frontend (nginx)
  -> Docker Gateway
       -> SimaticML XML / Blocks ZIP parser
       -> POST http://host.docker.internal:8015/export
            -> Windows Openness Worker (Python)
                 -> TIA Openness CLI
                 -> ZIP response
       -> POST http://host.docker.internal:8015/import   (write-back, HITL confirm)
            -> Windows Openness Worker
                 -> Openness XML/SCL import + fail-closed compile
                 -> JSON report
```

The worker is not proxied by nginx and is not reachable from the frontend. Its default
listener is host port `8015`; Docker reaches it through `host.docker.internal`. Because
that requires a non-loopback bind, keep port 8015 restricted by a Windows firewall to the
Docker/trusted workstation network.

## Supported Modes

| Mode | When to use it | Openness behavior |
|---|---|---|
| Full Docker + Worker | Normal Windows workstation with TIA Portal/Openness | `.zap`/`.apxx`/`.ap19` export is delegated to the local worker; XML/ZIP remains in Docker Gateway |
| Linux/XML-only | Linux, CI, or a machine without Openness | Worker URL is empty; upload SimaticML XML or a ZIP containing `Blocks/*.xml`; binary `.apxx` cannot be opened |
| HostGateway fallback | Diagnostics or a worker-code problem on a known Windows workstation | Container Gateway is stopped and host Gateway calls the Openness CLI directly; HTTP worker is not required |

`HostGateway` remains a fallback, not the long-term routing model. Prefer Full Docker +
Worker for normal Windows operation.

## Start And Verify

From the repository root:

```bat
Start-ResearchOS.cmd
```

The start script:

1. prepares the Openness CLI and firewall whitelist,
2. stops a stale worker by PID file,
3. starts `.venv\Scripts\python.exe -m industrial.openness_worker.server`,
4. generates and persists a worker token if one is absent,
5. waits for `GET /health`,
6. starts Compose with the worker URL and token injected into Gateway.

Runtime files:

```text
.researchos\run\openness-worker.pid
.researchos\logs\openness-worker.out.log
.researchos\logs\openness-worker.err.log
```

Verify the local worker:

```powershell
Invoke-RestMethod http://127.0.0.1:8015/health
```

Stop it with:

```bat
Stop-ResearchOS.cmd
```

The stop script terminates the PID in `openness-worker.pid` before stopping Compose.

## Configuration Map

| Variable | Consumer | Meaning |
|---|---|---|
| `RESEARCHOS_OPENNESS_WORKER_URL` | Docker Gateway | Empty disables remote export. Full mode uses `http://host.docker.internal:8015`. |
| `RESEARCHOS_OPENNESS_WORKER_TOKEN` | Worker and Gateway | Shared bearer token for `POST /export` and `POST /import`; generated locally if absent. |
| `RESEARCHOS_OPENNESS_WORKER_PORT` | Start script and worker | Local listener port; default is `8015`. |
| `RESEARCHOS_TIA_OPENNESS` | Gateway and worker process | Remains `off` for Docker Gateway; HostGateway and the worker set it to `cli` in their processes. |
| `RESEARCHOS_TIA_OPENNESS_EXE` | Openness preparation and worker | Path to the Windows CLI executable. |

Do not put the worker URL or token in `NEXT_PUBLIC_*` values. Do not add a worker location
to nginx.

## Security Boundaries

The worker is a local engineering-station capability, not a shared public service. Protect
it with the mandatory worker token and restrict port 8015 with a Windows firewall to the
Docker/trusted workstation network. It can open local TIA projects and execute the Openness
CLI, so it should run on a controlled Windows workstation or jump host rather than a
multi-tenant server.

Rotate `RESEARCHOS_OPENNESS_WORKER_TOKEN` by replacing its value in `deploy\env\.env` and
restarting the worker and Gateway. Treat `.env` as secret material.

## Upload Behavior

- `.zap`: unpacking it to an `.apxx` file is expected. The binary project is then sent to
  the Windows worker for Openness export.
- `.apxx`/`.ap17`/`.ap18`/`.ap19`: sent to the worker; unavailable without Windows
  Openness.
- SimaticML XML: parsed directly by Docker Gateway.
- ZIP containing `Blocks/*.xml`: parsed directly by Docker Gateway.

When the worker is disabled or unreachable, XML and ZIP ingestion continue. Binary project
export returns an actionable error asking the operator to start the Windows worker or use
the HostGateway fallback.

## Write-Back (`POST /import`)

The worker also closes the HITL write-back loop for Docker deployments. When the Gateway
confirms a changeset (`POST /api/v1/plc/jobs/{id}/writeback`) and
`RESEARCHOS_OPENNESS_WORKER_URL` is configured, `agents.plc.tia.writeback.execute_writeback`
delegates to the worker instead of failing with "Linux Docker cannot run Openness":

1. the client archives the target TIA project plus the staged bundle into one ZIP
   (`project/` + `import/` with `import/external_sources/*.scl`);
2. `POST /import` (bearer token, query `plc_name`, `compile_after`) extracts it, resolves
   the complete `.apxx`, and runs the exact same `execute_writeback` logic on Windows —
   including the Safety/F-block refusal and the fail-closed `ICompilable.Compile` gate;
3. the JSON report (`ok`, `imported`, `scl_imported`, `compile`, per-file `results`) is
   returned to the Gateway and stored on the job as in HostGateway mode.

Exports and imports serialize on one shared lock because they drive one TIA Portal
instance. `.zap` archive after a successful write-back remains a HostGateway/follow-up
capability — the worker currently stops at import + compile.
