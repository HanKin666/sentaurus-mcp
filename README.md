# Sentaurus MCP

Standalone MCP server for native Sentaurus batch experiments. No private research dashboard, server credentials, proprietary examples, or real experimental data are included or required.

## Architecture

MCP client -> thin STDIO tools -> persistent experiment service (SQLite) -> independent Worker -> detached runner -> operator-configured SDE / SDevice / SVisual executable.

The native experiment directory contains original inputs, a manifest with SHA-256 fingerprints, stage logs, output files, and final execution status. Multiple experiments share a project folder but have isolated directories. This is **not** a generated Sentaurus Workbench `.gproject` project.

## Install

Python 3.10+:

```sh
python -m venv .venv
# Activate the environment for your platform.
python -m pip install -e '.[test]'
python -m pytest -q
```

Copy `examples/config.example.json` to a private location, configure an absolute data root and installed tool paths. Set `SENTAURUS_MCP_CONFIG` to that file. Start `sentaurus-worker` separately (for example as a service or in a dedicated terminal), then start `sentaurus-mcp` from the installed environment. Never start the Worker as a child of the MCP client. Set `SENTAURUS_ENABLE_ACTIONS=1` explicitly to enable preparation/submission. Default is read-only.

Client configuration:

```json
{
  "mcpServers": {
    "sentaurus": {
      "command": "/absolute/path/.venv/bin/sentaurus-mcp",
      "env": {
        "SENTAURUS_MCP_CONFIG": "/absolute/private/config.json",
        "SENTAURUS_ENABLE_ACTIONS": "0"
      }
    }
  }
}
```

On Windows use `.venv/Scripts/sentaurus-mcp.exe`. On a Linux simulation server install the package there; a client can run the STDIO executable over its operator-configured SSH connection. No SSH credentials are embedded in this package. The supplied profiles are examples; verify executable flags against your installed Sentaurus release.

## Tools

- `create_experiment(project, run_id, files, stages)`: prepare text inputs; each stage has `tool` and `input_file`. No execution.
- `submit_experiment(run_id)`: atomically enqueue an experiment; the independent Worker launches it. Returns immediately. Duplicate submission never restarts a non-prepared run.
- `list_experiments(offset, limit)`: persistent history.
- `get_experiment(run_id)`: execution state, input manifest, process IDs, timing, validation label.
- `read_log(run_id, stage_index, offset, limit)`: incremental bytes, bounded response.
- `list_artifacts(run_id)`: file index without embedding large data files.

`sentaurus://capabilities` exposes the implemented scope.

## Runtime semantics

No fixed wall-clock solver timeout. Normal MCP shutdown does not cancel a detached simulation. An HTTP/MCP timeout is not a solver failure. Query the existing experiment before taking further action. SQLite serializes queue insertion and Worker launches, enforcing `max_parallel` (default 1). The Worker heartbeat is checked before accepting new submissions. Inputs are hashed and checked before submit.

The service records wall-clock stage durations and minimal host information. It does not yet collect per-process memory peaks or full hardware inventory. `completed` means stage processes exited successfully, **not** numerical or physical acceptance.

## Limits of v0.1

Real Sentaurus execution requires a licensed installation. Automated tests use synthetic Python processes, not physical simulation. Native SWB project creation, automatic license/resource-budget admission, cancellation, host-reboot/crash recovery, TDR parsing, metric extraction and ZIP export are not implemented. Existing private-workbench features are not claimed as public MCP features.

After an abnormal host/runner crash, `starting/running` may remain stale; inspect the process and logs before manually reconciling. Never clear those states just to bypass concurrency limits. Run under an appropriate scheduler/OS account for CPU and memory constraints. Uploaded input scripts execute with that account's authority; the configured root and no-shell launch are **not a script sandbox**. Use trusted clients only.

## Development and release

Tests cover actual STDIO discovery, independent-Worker execution after client exit, duplicate/concurrent submit handling, input changes and path restrictions. See `VALIDATION.md`. GitHub CI uses synthetic tasks only.

The release ZIP is built from an explicit source-file list, excluding the virtual environment, databases, configuration and simulation outputs. This draft intentionally has no open-source license until the project owner chooses one; no third-party source has been copied.

Architecture references (independent implementation):
- https://github.com/ansys/pymechanical-mcp
- https://github.com/ansys/pyaedt-mcp
- https://github.com/SciMate-AI/openfoam-mcp
- https://github.com/modelcontextprotocol/python-sdk

Uses official MCP Python SDK v1 API with `<2` compatibility bound. This project is unofficial and is not endorsed by Synopsys.
