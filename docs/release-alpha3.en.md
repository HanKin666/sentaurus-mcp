# Alpha.3 Release Notes

**Status: prerelease test version.** Tag: `v0.1.0-alpha.3`; Python package: `0.1.0a3`.

## Why it is still alpha

Alpha.3 is a software prerelease candidate. Current coverage includes one Windows local MCP/Worker environment and one Linux native Sentaurus execution path. The real tool run used an SSH tool adapter configured separately by the operator; the adapter is not included in the release package. Direct Linux-hosted MCP deployment has not been verified, recovery coverage is limited, and there is no cross-platform or cross-dependency compatibility matrix.

The prerelease status reflects narrow software deployment and runtime coverage. Alpha is a software-maturity label and makes no judgment about scientific conclusions; the single small smoke test is not a device research result, model calibration, or physics acceptance.

## Changes

- Add fresh execution observations and bounded failure diagnostics, with checks for expected output files.
- Export one or more finished experiments as ZIP archives with per-file integrity information.
- Add read-only native-project indexing, named-column ASCII PLT reads, and figure provenance.

Features correspond to this version of the release assets and source revision.

## Validation summary

- Original regression suite: 33 passed, 1 skipped, 0 failed.
- Separate synthetic client scenarios: 6 passed; these are not included in the regression-suite count.
- Real software smoke test: Sentaurus T-2022.03 native tools completed one single-bias silicon-resistor flow with 10 × 1 µm geometry. See the [validation record](../VALIDATION.md) for the scope and summarized outputs.

The [validation record](../VALIDATION.md) describes the tested environment and limits. Only [generic example decks](../examples/smoke/README.md) are provided. Actual connection settings, native outputs, logs and run records remain private and are excluded from the release package.
