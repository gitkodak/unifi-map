# Releasing

What actually happens when a version goes out, written down after doing it by
hand rather than invented in advance, and corrected each time it turned out to
be wrong.

This describes the process as it exists. One thing about it is deliberately
undecided, and that is called out at the end rather than quietly assumed.

## Deciding whether to release at all

`CHANGELOG.md` holds the rule for which number moves. In short: patch for fixes,
minor for anything new or, while pre-1.0, for **a renamed flag or a changed
default**, major once the interface is declared stable and something breaks.

Those last two are easy to talk yourself out of, and 0.5.0 nearly shipped as
0.4.2 on the grounds that nothing visibly broke. Renaming `--layout sane` and
refusing a multi-site support file that used to be mapped are both squarely the
"would otherwise be breaking" case, and a rule bent once is worth less next
time.

Two things argue for cutting a release rather than letting `Unreleased` grow:

* **Security fixes should not sit unreleased.** Anyone tracking tags is running
  the last one.
* **A long `Unreleased` section is where changelog drift happens.** It has had
  to be repaired before release, and the cause has always been the same: an
  edit anchored on text that appears in more than one place.

## Before you start

```bash
make check
git status --porcelain      # must be empty
```

**Grep for the version you are about to cut**, before cutting it. A version
number gets promised things in passing, in code comments and docs as much as in
the changelog, and those promises scatter. 0.5.0 was owed both a man page and
the removal of `sane`; the second turned out to be unmeetable in the very
release that introduced its replacement, which is the kind of thing better
found now than after the tag exists.

```bash
grep -rn "0\.5\.0" --include="*.md" --include="*.py" .
```

**Read `TODO.md` and correct it.** It is the answer anyone gets to "what is
coming?", and it is the file with no test behind it: it describes intentions, and
a test that checked its shape would only force the shape rather than the truth.
Every release is the promised moment to look. Specifically:

* Anything shipped in this version comes out.
* Anything that turned out to be a bad idea moves to "considered and not
  planned", with the reason. That section is worth more than the rest, because
  it is what stops a settled question being reopened.
* The "committed to a version" section names only versions not yet released.

Read `## Unreleased` in `CHANGELOG.md` end to end. Specifically confirm:

* Every entry is under exactly one `### Added`, `### Changed` or `### Fixed`.
  Repeated headers mean entries were inserted against different anchors.
* Nothing you added recently has landed **inside an already-released section**.
  This has happened, in both directions: a released version claiming a feature
  it does not have, and the new version missing its headline one. Check by
  looking at the heading above each new entry, not by trusting where you meant
  to put it.

## Cutting it

1. **Date the section, and keep `## Unreleased`.** Insert a new
   `## X.Y.Z - YYYY-MM-DD` heading *below* it and move the entries down. Do not
   rename `Unreleased` away: `CONTRIBUTING.md` tells contributors to file
   changes there, and an absent section was raised as a defect by an external
   review.

2. **Bump the version.** `src/unifi_map/__init__.py` only. `pyproject.toml` reads
   the attribute, so there is exactly one number and never two to keep in step.

3. **`make docs`.** Not optional, and it must come after both steps above. The
   flag reference and the man page are generated, and the man page carries the
   version *and* takes its date from the changelog entry for that version.

   Bumping without regenerating fails `make check`. Bumping *before* dating the
   section is worse: the page generates with an empty date and the
   regenerate-and-compare check cannot see it, because both sides are generated
   the same wrong way. `test_the_man_page_header_carries_a_date` exists for
   exactly that, and is the reason this order is load-bearing rather than a
   preference.

4. **`make demo-images`**, if anything changed how a map is drawn. The
   screenshots in the README are committed, so they go stale silently: nothing
   fails, the picture is just wrong. They had drifted noticeably by the time
   regenerating them was scripted. The same run also regenerates
   `docs/demo-light.html` and `docs/demo-dark.html`, the committed copies of
   the interactive viewer.

5. **`make check`.** A test asserts the changelog has a section matching
   `__version__`, so bumping without a changelog entry fails here rather than
   after the tag exists.

6. **Push to `validate` and read it rendered.** The changelog and README are the
   parts of a release most likely to be wrong, and they are the parts a diff
   shows worst. See the publishing order in `CLAUDE.md`.

7. **Push to `origin`, then tag, then push the tag.**

   ```bash
   git push origin main
   git tag -a vX.Y.Z -m "…"      # annotated, summarising the headline changes
   git push origin vX.Y.Z
   ```

   In that order. Tagging a commit that is not yet on the remote works locally
   and confuses everything afterwards.

8. **Publish the GitHub Release**, from the changelog section for this version.

   ```bash
   # The section body, without its `## X.Y.Z - DATE` heading.
   gh release create vX.Y.Z --title vX.Y.Z --notes-file notes.md --verify-tag --latest
   ```

   **A tag is not a Release.** They are separate objects: a tag leaves the
   Releases sidebar empty, publishes no notes page, and reports nothing to
   anything querying `/releases`. Eleven tags existed before the first Release
   did, and an external repository scanner reported the project as having no
   releases at all, which was fair.

   Use the changelog section as the body rather than a link to it. Someone who
   arrives at a release page has already navigated to the version they care
   about, and sending them elsewhere to find out what changed is the whole
   thing they came for.

   `--verify-tag` refuses to invent a tag that does not exist, which is what
   keeps this step honest about following step 7 rather than replacing it.

9. **Mirror to GitLab.**

   ```bash
   ~/Development/admin-scripts/scripts/mirror-github-to-gitlab.sh -q unifi-map
   ```

10. **Verify, rather than assume.** All four refs at the same commit, the tag on
   both remotes, the tag pointing at the version you think it does, and the
   Release present and marked latest.

   ```bash
   git rev-parse --short HEAD
   for r in validate origin gitlab; do
     echo "$r $(git ls-remote $r refs/heads/main | cut -c1-7)"
   done
   git ls-remote --tags origin | grep -oE 'v[0-9.]+$' | sort -uV
   git show vX.Y.Z:src/unifi_map/__init__.py | grep __version__
   ```

   Then wait for CI rather than assuming it:

   ```bash
   gh run watch "$(gh run list --limit 1 --json databaseId -q '.[0].databaseId')" --exit-status
   gh run view "$(gh run list --limit 1 --json databaseId -q '.[0].databaseId')" \
     --json conclusion,jobs -q '.jobs[] | "\(.conclusion)\t\(.name)"'
   ```

   Check the per-job output, not only the overall result. `Dependency
   advisories` is `continue-on-error`, so it reports success having failed
   inside, which is deliberate but means the summary line is not the whole
   story. If `gh` is unavailable on the machine you are releasing from, say CI
   is unconfirmed rather than reporting a green build nobody saw.

## Things that have actually gone wrong

* **The test count in `AI_DISCLOSURE.md` goes stale.** It is checked by a test,
  so this surfaces as a failure rather than a lie, but expect to update it.
* **Dependabot may have merged something.** A push can be rejected as
  non-fast-forward. Rebase onto it; do not force.
* **Changelog entries landing in the wrong section**, as above. This is the most
  likely mistake and the least likely to be noticed.
* **The installed editable metadata lags the source.** `--version` reads
  `__version__` directly and is right immediately, but
  `importlib.metadata.version("unifi-map")` reported `0.1.0` long after the
  source said otherwise. Harmless locally, misleading if you are checking that
  a build picks the version up:

  ```bash
  pip install -e . --no-deps -q
  ```

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

**There is no published artifact.** A release here is a tag, a changelog entry
and a GitHub Release carrying that entry.

Building one locally is not the undecided part and is documented: `make build`
produces a wheel and an sdist in `dist/`, and `pip install dist/*.whl` works
anywhere. Nothing about that is a promise to anyone, which is exactly why it
sits outside this section.

Note that the Release itself is not the undecided part, and stopped being
optional at 0.8.0: it costs nothing, breaks no promises, and is what makes the
version history visible from outside a checkout. What is still undecided is
whether anything should be *attached* to one.

Whether that should change is a real decision, not an oversight:

* Publishing to PyPI means owning the name, keeping metadata honest, and never
  breaking a published artifact. It also makes `pip install unifi-map` work,
  which is what people expect of a Python tool.
* The entry point and build backend already exist, and `make build` drives
  them, so there is no build work left in either direction. CI would need a
  `tags:` trigger to build and attach or upload them.
* Graphviz is a system dependency, so a wheel is not self-contained either way.
* Since 0.5.0 there is a man page, which packaging would have to place in
  `share/man/man1` for `man unifi-map` to work rather than `man ./unifi-map.1`.
  That is a small amount of work and one more thing to keep correct, so it
  belongs on this side of the decision rather than being discovered after it.

Until that is decided, this file describes a tag-and-changelog release, and says
so rather than implying more.
