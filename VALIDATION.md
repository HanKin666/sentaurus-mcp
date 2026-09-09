# Validation — 2026-09-09

- Environment: Windows, Python 3.12, official MCP SDK 1.30.0, pytest 8.4.2.
- Synthetic service and actual STDIO protocol tests: 5 passed.
- Actual MCP initialization, tool discovery, create and submit calls exercised.
- Independent Worker completed synthetic task after MCP client shutdown.
- Concurrent duplicate submit created only one queued attempt.
- Input fingerprint change and invalid identifiers rejected.
- max_parallel=1 serialized two tasks; nonzero subprocess exit retained as failed.
- State survived a new Service instance; logs and unreviewed quality label verified.

An earlier prototype spawned runners directly from MCP. The Windows MCP client's Job Object cleanup terminated that child. The final implementation uses an independently started Worker, and the disconnect test now passes.

No real Sentaurus execution, license validation or physical-result acceptance was performed. Linux CI is provided but has not run remotely. No public GitHub repository has been created or pushed by this task. Private dashboard data and current simulation are outside this repository and these tests.
