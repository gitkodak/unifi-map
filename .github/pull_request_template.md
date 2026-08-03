## What this changes

<!-- What changed, and why. If it fixes something subtle, say what it was. -->

## Checklist

- [ ] `make check` passes (`ruff format --check`, `ruff check`, `pytest`), and I
      checked its exit code rather than eyeballing piped output
- [ ] Tests added or updated, and none of them touch the network
- [ ] Any new fixture data is non-identifying: no real hostnames, subnets, SSIDs
      or device addresses
- [ ] No Ubiquiti artwork vendored into the repository
- [ ] No `cache/` or `out/` contents committed
- [ ] If this changes what gets drawn, the legend and the docs still describe
      it accurately (`docs/usage.md` for layouts and reading the diagram,
      `docs/output.md` for formats)

## Anything you are unsure about

<!-- Open questions, or a decision in CLAUDE.md you think is wrong. Both welcome. -->
