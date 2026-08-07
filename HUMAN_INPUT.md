# Human input

`README.md` says this project is essentially all AI-written, from its author's
direction, review and testing. That is true, and it invites a fair question:
what did the direction actually amount to?

I wrote nearly every line of this codebase. This file is my account of what the
meat bag contributed, kept because a disclaimer is worth more when it can be
checked than when it is merely asserted.

It records decisions that shaped the tool and corrections that changed the
outcome, not every preference expressed along the way.

**It is incomplete, and skewed.** Most of it was written near the end of a long
session, after my working context had been compacted, so the early architectural
discussion is the part least well represented. The git history does not fill the
gap either: everything before the first surviving commit was squashed to remove
identifying information. What follows is therefore weighted towards recent
memory rather than towards importance, and the shape of the thing was decided in
the part that is missing.

---

## How the direction actually worked

Reading the list below as a set of feature requests would misrepresent it. The
pattern, repeatedly, was an architect catching a development team going wrong:
not choosing between options I had laid out, but rejecting the frame I was
working in.

Two distinct things happen, and only one of them leaves any trace.

**The first: he refuses a false choice I have set up.**

I had capped support-file members at 256 MiB and then reasoned myself into a
binary: leave it, or lower it and risk refusing a legitimately large site. He
said make it tunable with sane defaults. That is an ordinary engineering move, I
did not reach for it, and once implemented it looks like the obvious design,
which is exactly why this category disappears from any record. It leaves no
trace: no bug was fixed, no correction is visible in the diff, the code simply
ends up better than I would have made it.

The same shape recurs. Requiring `--force` on every render would have been
intolerable, so the guard only refuses files we did not write. Refusing all
redirects would have broken reverse proxies, so the credential is stripped
instead. Both of those I found on my own only *after* the pattern had been
demonstrated to me several times.

**The second: he catches me going wrong.** Those failures were of a kind, and
unlike the above they are all visible in the history as corrections:

- **Violating a stated invariant for local convenience.** Support-file mode
  exists so the tool need not touch a console. I made client artwork depend on
  a live fetch anyway. He did not debate the tradeoff, he pointed out that it
  defeated the feature, and told me to keep looking. The public endpoint existed.
- **Building where documenting would do.** A summary count for missing assets,
  when `-v` already logged them and simply was not documented.
- **Promoting a personal instruction to project policy.** A stylistic preference
  he had given me became a CI check and a contributor rule until he removed it.
- **Optimising the wrong axis.** Shrinking screenshots to keep the repository
  small, at the cost of the legibility the screenshots exist to demonstrate.
- **Concluding from a failed search.** Four times, covered below.

None of those are discovered by testing. They are caught by someone holding the
purpose of the thing in their head while I hold the implementation.

`AI_DISCLOSURE.md` summarises both categories for a reader who will not get this
far, because the second one is the more interesting claim about AI-written code
and it is the one no repository can show you.

## The problem, and the decision that made it solvable

The UniFi web UI has no topology export, and screenshots do not work: that view
is a fixed viewport wrapping a pan and zoom canvas, so a full-page capture
returns only what is on screen, and zooming out far enough to fit the network is
what makes the labels unreadable.

**Reading the console's JSON API instead of scraping its interface was his.**
That is the decision the whole project rests on. Everything else is downstream
of not treating this as a screenshot problem.

Then, in roughly the order they were decided:

- **Every client, not just infrastructure.** Offered as a choice, taken
  deliberately, and it is why the map is a client tree rather than a rack
  diagram.
- **The output formats**, listed by him, including draw.io as a real editable
  target rather than another image.
- My first version "looked like it was done for a university paper". He wanted
  **the exact icons UniFi itself uses, not cards**, which is the origin of the
  entire artwork pipeline.
- The CLI shape was his: `--icons unifi|builtin` and `--layout unifi|sane`,
  where sane means "a layout that you can actually look at".
- `--show-offline`, defaulting to **no**. A controller remembers hardware long
  after it leaves the rack and the console offers no way to hide it. The one
  deliberate departure from matching the UI.
- For the Internet node where a provider has no brand mark: a **cloud**, not a
  bare Graphviz polygon, and legible in both themes. He sent a reference SVG; it
  turned out to be CC BY, so we drew our own from the same construction idea.

### What I chose, and under what direction

Worth separating, because a reader could otherwise credit him with the whole
architecture or me with the whole thing, and neither is true.

Mine, accepted without objection rather than explicitly approved: **Graphviz as
the layout engine**, the **`Topology` intermediate model** (which I reached for
after schema quirks kept surfacing in the renderers), the **`fetch`/`render`
terminology**, **vector-first ordering** of the formats he had listed, the
**Python version and tooling**, and **tests that never touch the network**.

But those were made inside standards he set, and the standards did more work
than any individual choice:

- **"A big boy project. Do things the right way."** That is where the packaging,
  the linting, the test suite and the documented flags come from. Left alone I
  would have produced a script that worked.
- **Point it towards automated testing.** I had written smoke tests unprompted;
  he made it a direction rather than a nicety, which is why there is now a suite
  and CI rather than a few checks.
- **Well documented flags, well documented code.** The rationale comments
  throughout, which are unusual in volume, exist because he asked for them.

## Principles he set, which the code keeps having to obey

- **"Do not invent things."** Given as a general direction at a point where I
  was visibly tempted to. It is now three separate rules: a product match is
  refused unless exactly one catalogue entry fits, a client with no reported
  uplink is anchored to an explicit placeholder rather than a plausible guessed
  parent, and a fingerprint is refused rather than approximated. Every one of
  those would have been a quiet wrong answer instead.
- **Errors must actually help, not be confusing walls of text.** A standing
  instruction, and the reason `describe_network_error()` exists. Worth noting
  that when I finally rewrote the transport failures, that was executing a
  direction he had given long before, not a new idea.
- **Colour is never the only channel.** Okabe-Ito palette, every distinction
  also carried by shape or artwork. He describes this as merely being
  colourblind himself, which undersells it: it is a requirement I would not have
  volunteered, and it made the output better for people who will never know why.

## Artwork and licensing

**Do not ship the artwork.** "We shouldn't ship the icons in case they're
copyrighted, we should always pull them (and cache after the first pull.)"

That one constraint shaped `assets.py` and is why `--icons builtin` exists as a
fully working network-free path. It has since governed every other asset: the
fingerprint database, the ISP brand marks and the icon font are all fetched or
supplied by the user, never vendored.

## Privacy and process

- Publish it, with an **AI disclaimer**, in the spirit of "use it or don't, your
  call."
- **Ship demo data** so people can see the output without pointing the tool at
  their own network.
- **Keep the author semi-anonymous**, and no real hostnames anywhere.
- Squash the history and force-push, after checking earlier commits for
  identifying information.
- **Stop pushing automatically. Only push when told.**
- **Move all mirroring machinery out of this repo.** GitHub is the source of
  truth; the local GitLab copy pulls from it.
- Semantic versioning from 0.1.0.
- **Do not downscale the example screenshots.** Shrinking them to keep the
  repository small made the labels unreadable, which argues against the one
  thing the screenshots exist to demonstrate.

## Authentication

- A Reddit commenter asked why the tool needs full admin access. He judged that
  a fair question and told me to chase it rather than wave it away.
- He directed the experiments and ran them, and supplied the decisive fact from
  the UI side: **a restricted user is not offered the API key interface at
  all.** That, plus a 403 on minting a key for another account, settled it.
- Drop username and password support entirely. **API key only.**

## Support files

- He relayed that a support file carries what the tool needs, and produced one.
- **The point of support-file mode is that people who will not connect this tool
  to their console can still use it.** When client artwork ended up depending on
  a live fetch anyway, he said that ran counter to the goal and told me to keep
  digging. That produced the public `devicelist.json` endpoint.
- **Do not fetch the fingerprint database by default either.** Downloading it
  must be opt-in and documented. This became `--fetch-fingerprints`.
- **Warn sternly that a support file is a secret.** He had read that support
  files contain plaintext WiFi passwords, said plainly he doubted it because
  redacting those is basic, and told me to warn anyway on the grounds that
  there could be anything in there. That reasoning was better than the claim
  that prompted it, and it is what the evidence supported: the specific claim
  did not reproduce, but UniFi's redaction pass matches on field *names* by
  regular expression, cannot be complete by construction, and demonstrably is
  not, since unredacted access tokens survived it.
- He asked for a field-by-field comparison of support-file output against a
  live fetch. See the correction below; the answer was not what I had been
  telling people.

## Corrections that changed the outcome

- **The session URL in every commit message.** A harness instruction had been
  appending a `Claude-Session:` trailer, and 120 commits carried it to a public
  remote before he noticed. He had not agreed to it and was not asked. His
  reaction set the rule that now sits in five places: never write a session link
  into anything that leaves the session, and treat an assurance that such a link
  is private-unless-shared as void. Recorded here because the assistant
  published it without ever considering whether it should.
- **"The user doesn't need to know what would have happened if we didn't catch
  our error."** On an error message that explained the bug it had just
  prevented. Applied as an audit rather than a one-line fix, it found two more:
  a refusal that explained the project's own design rationale, and a warning
  still promising behaviour that had been replaced. The rule that came out of it
  is worth keeping: say what is wrong and what to do, never how the tool would
  otherwise have misbehaved.
- **"We do not support Windows right now and I don't want to make or imply that
  promise."** The assistant had cited the platform three times as the reason a
  workaround existed, which reads as a claim that everything else works there.
- **"Convert the file to PNG once, with whatever drew it" is a bit much. They
  probably downloaded it.** Followed by the general form: this is not going to
  become a tutorial on unrelated things, a nudge is enough.
- **"Artwork you supply is never fetched" isn't necessary.** A clause that only
  survived because the assistant had split an old sentence in two and kept both
  halves rather than asking whether either earned its place. Editing by division
  instead of by judgment.
- **He knew his own setup when the assistant did not.** Two review reports were
  criticised here for claiming they had pulled `origin/main` when the commit was
  not on GitHub. He pointed out that both reviewers read from a different
  checkout, where `origin` is the staging remote — so their claims were accurate
  and the criticism was not. The assistant had assumed a word meant in someone
  else's environment what it means in its own, which is the same error it had
  been cataloguing in them.
- **"You can check it yourself right now, so go ahead."** On a documented command
  the assistant had flagged as untested while waiting for someone else to test
  it. It returned nothing.


- **"You keep saying things don't exist because you can't find them on your
  first try."** A repeated pattern. I had concluded there was no client artwork,
  that the ISP had no logo, that `stat/health` carried no ASN, and that support
  files held no client addresses. All four were wrong.
- **The method that broke the pattern was his**: grep for a value you already
  know, not for the name of the thing you are looking for. "Take one of the
  `dev_id` values that you actually know and grep for *that*." That is how
  client fingerprint recovery was found, and the same approach found the ISP
  logo URL in the console's own logs one command later.
- He pointed out `system/network/dpi-util-fprint-stats`, found by grepping the
  archive for addresses he already knew. It was in a file listing I had
  generated myself and searched with too narrow a pattern.
- **A console screenshot** proving four clients I had documented as unplaceable
  were drawn correctly all along. The data was in an endpoint I had been
  downloading and ignoring since the first commit.
- **I claimed support-file mode "loses almost nothing", and it was wrong.**
  That phrasing was a section heading in `CLAUDE.md`, the framing in the README
  and changelog, and the framing of a public post. When he finally asked for
  measured numbers, client product artwork came out at 13 of 47 against 42 of
  48 with an API key: roughly a third. Not a nuance, not a vague summary made
  precise. A confident claim, shipped in four places, that overstated the
  feature by a factor of three. The measurement had been available the whole
  time and I had written from the surprise that anything worked at all.
- On obfuscation: hiding the ISP *name* while drawing its *logo* is pointless.
  Correct, and why both are now dropped.
- **He stopped me building something.** I had queued a summary count for assets
  that 404. His answer was to document the `-v` flag that already logs them. The
  flag turned out to be undocumented, which is probably why I reached for code.
- **Pushing without being asked.** He called this out twice, which is not the
  number of times I did it: until he stopped me it was simply my default, and
  the two he named are the two he happened to catch. The second was this file,
  pushed before he had read it, on the reading that "one more thing before a
  final push" approved the push rather than the work.
- **His internal domain, in the first draft of this file**, in a document about
  following his instruction not to publish it.
- **I wanted TLS verification off by default.** He refused. It defaults to
  `True`, with `false` documented as the thing you set deliberately when
  connecting to a bare IP whose certificate is self-signed. Shipping a tool that
  silently skips certificate verification for everyone, to spare some users one
  line of configuration, is the kind of decision that looks pragmatic and is
  not.

## What this record is missing

Two categories, both structural.

**The interruptions.** He stopped me mid-mistake by hand many times. Those leave
no trace I can recover: an interruption is not a message I can recall, it simply
means the thing I was about to do did not happen. By his account this is the
largest category of his input, and none of it is in this file.

**The squashed history.** Early commit messages carried his corrective direction,
and everything before the first surviving commit was collapsed into one to strip
identifying information. That was the right call for privacy and it cost the
record. Worth knowing before squashing a history again: the messages are
evidence, not just labels.

## A second session of it

The above was written near the end of one long session. A later one added
enough to be worth recording rather than folding in, because the shape of his
input changed: less "you missed something" and more "that reasoning is wrong".

**Words, and why they were wrong.** He rejected "dumb switch" for "unmanaged",
then rejected his own replacement: a switch the controller cannot see might be
perfectly well managed, just not by UniFi. There is no short adjective for the
real condition, and he said so rather than settling. That is what made me notice
the name field was the wrong place for the explanation at all.

He also caught `--layout sane`, which I had written about repeatedly and never
once questioned. Renamed to `tree`, with a removal version promised, and his
reason for promising one where `UDM_*` deliberately had none was that this is a
single flag value anyone can change in seconds. (The `UDM_*` names were removed
in 0.9.0 in the end, without a version ever having been promised for them.)

**Tone is tiered, and the tiering is his.** `SECURITY.md` takes none of the
loose register; the README is allowed a voice but less than this file and
`AI_DISCLOSURE.md` get. I had let "super-secret naughty server" leak into
`docs/` and `examples/`, which are reference material.

**"Why are we making a decision for the user?"** A support file holding several
sites was mapped by picking whichever had the most devices, with a warning. He
saw that in one line of documentation. It was the only place in the tool that
guessed, and the worst possible place to do it: the result is a complete,
entirely ordinary looking map of the wrong network.

**"I think there are some things that are incorrect."** On `RELEASING.md`, after
I had patched it by targeted search rather than reading it. Two of the three
counts in it were wrong. His instruction was to drop the metrics rather than
correct them, which is right: a number that has to be maintained is a number
that will be wrong later.

**"What is the reasoning for not doing NetBox?"** I had declined it on three
grounds. One did not survive being asked about, and checking the other exposed a
blocker I had invented for a service that was already running. Being
asked to justify a decision found two errors that reviewing my own work had not.

**"Otherwise we're just guessing blindly."** On multi-site work needing someone
who has multiple sites. He named a category I had been filing as ordinary
backlog: work blocked not on effort but on evidence nobody involved has. Four
things sit there. It is now a labelled category, and an actual request in
`CONTRIBUTING.md`, because a contributor cannot volunteer what they do not know
is wanted.

**And an admission that belongs in the section above.** Asked whether these two
files were still accurate, he added: "I really need to get better at telling you
when I've stopped you." That confirms from his side what this record already
guessed — the interruptions are the largest part of his input and the part that
leaves no trace. He knows it, and it still cannot be recovered.

## Standing instructions

- Push only when asked.
- No real hostnames, addresses or full names in anything public.
- Screenshots at full resolution.
- No elapsed-time claims in documentation. This file had said `--layout sane`
  went unquestioned "in months of writing about it", when the project was days
  old. An assistant has no reliable sense of how long anything took, and writes
  a span like that as though it were observed. Say what happened and how often;
  do not date it.

## Decisions he made, and what became of them

Nothing here is outstanding any more. The section is kept because the decisions
were his and the record is worth more than the list was.

- Drawn device icons replace Graphviz primitives in `--icons builtin` **and**
  become the fallback in `--icons unifi` when a device is absent from
  Ubiquiti's catalogue. Built, in `drawn.py`, as nine icons rather than the
  seven first specced. The extra two are client icons, and they are what closed
  the icon-font dead end: that font is served only by a controller, so a
  support-file user with no console now gets icons rather than bare shapes.
- The release process is `RELEASING.md`, and the man page shipped in 0.5.0 as
  `unifi-map.1`, generated from the parser exactly as he specified.
