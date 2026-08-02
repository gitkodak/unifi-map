# Releasing

What actually happens when a version goes out, written down after doing it twice
by hand rather than invented in advance.

This describes the process as it exists. One thing about it is deliberately
undecided, and that is called out at the end rather than quietly assumed.

## Deciding whether to release at all

`CHANGELOG.md` holds the rule for which number moves. In short: patch for fixes,
minor for anything new or, while pre-1.0, for a changed default, major once the
interface is declared stable and something breaks.

Two things argue for cutting a release rather than letting `Unreleased` grow:

* **Security fixes should not sit unreleased.** Anyone tracking tags is running
  the last one.
* **A long `Unreleased` section is where changelog drift happens.** Both times
  the section had to be repaired before it could be released, and both times the
  cause was an edit anchored on text that appears in more than one place.

## Before you start

```bash
make check
git status --porcelain      # must be empty
```

Read `## Unreleased` in `CHANGELOG.md` end to end. Specifically confirm:

* Every entry is under exactly one `### Added`, `### Changed` or `### Fixed`.
  Repeated headers mean entries were inserted against different anchors.
* Nothing you added recently has landed **inside an already-released section**.
  This has happened, in both directions: a released version claiming a feature
  it does not have, and the new version missing its headline one. Check by
  looking at the heading above each new entry, not by trusting where you meant
  to put it.

## Cutting it

1. **Bump the version.** `src/unifi_map/__init__.py` only. `pyproject.toml` reads
   the attribute, so there is exactly one number and never two to keep in step.

2. **Date the section.** Rename `## Unreleased` to `## X.Y.Z - YYYY-MM-DD`.

3. **`make check`.** A test asserts the changelog has a section matching
   `__version__`, so bumping without a changelog entry fails here rather than
   after the tag exists.

4. **Push to `validate` and read it rendered.** The changelog and README are the
   parts of a release most likely to be wrong, and they are the parts a diff
   shows worst. See the publishing order in `CLAUDE.md`.

5. **Push to `origin`, then tag, then push the tag.**

   ```bash
   git push origin main
   git tag -a vX.Y.Z -m "…"      # annotated, summarising the headline changes
   git push origin vX.Y.Z
   ```

   In that order. Tagging a commit that is not yet on the remote works locally
   and confuses everything afterwards.

6. **Mirror to GitLab.**

   ```bash
   ~/Development/admin-scripts/scripts/mirror-github-to-gitlab.sh -q unifi-map
   ```

7. **Verify, rather than assume.** All four refs at the same commit, the tag on
   both remotes, CI green.

   ```bash
   git rev-parse --short HEAD
   for r in validate origin gitlab; do
     echo "$r $(git ls-remote $r refs/heads/main | cut -c1-7)"
   done
   git ls-remote --tags origin | grep -oE 'v[0-9.]+$' | sort -u
   ```

## Things that have actually gone wrong

* **The test count in `AI_DISCLOSURE.md` goes stale.** It is checked by a test,
  so this surfaces as a failure rather than a lie, but expect to update it.
* **Dependabot may have merged something.** A push can be rejected as
  non-fast-forward. Rebase onto it; do not force.
* **Changelog entries landing in the wrong section**, as above. This is the most
  likely mistake and the least likely to be noticed.
* **A stale `__pycache__` can outlive a version change.** If a test insists the
  version is something the source file plainly does not say, the bytecode is
  older than the edit:

  ```bash
  find src tests -name __pycache__ -type d -exec rm -rf {} +
  ```

  Seen while deliberately breaking the version to prove the check above works.
  Worth knowing because the symptom, a test disagreeing with a file you are
  looking at, invites you to doubt the test.

## The undecided part

**There is no published artifact.** A release here is a tag and a changelog
entry. The only documented install is a clone plus `pip install -e .`.

Whether that should change is a real decision, not an oversight:

* Publishing to PyPI means owning the name, keeping metadata honest, and never
  breaking a published artifact. It also makes `pip install unifi-map` work,
  which is what people expect of a Python tool.
* The entry point and build backend already exist, so `sdist` and `wheel` need
  no new machinery. CI would need a `tags:` trigger to build and attach them.
* Graphviz is a system dependency, so a wheel is not self-contained either way.

Until that is decided, this file describes a tag-and-changelog release, and says
so rather than implying more.
