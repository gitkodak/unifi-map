# AI disclosure

Nearly every line of this project was written by an AI assistant. This file says
what that means concretely, what it does and does not imply about the code, and
where to look if you would rather check than take anyone's word.

It exists because "AI-assisted" has become a label that can mean anything from
autocomplete to the whole thing, and the difference matters to somebody deciding
whether to run this against their own network.

## Who wrote what

- **The code, tests and documentation: the assistant.** All of it, including
  this file.
- **The direction, review, testing and every decision about what the tool
  should be: a human.** He decided what it should do, what good looked like,
  what was out of scope, and repeatedly what was wrong.

That is not a formality. `HUMAN_INPUT.md` is a specific record of that
direction, including the parts where he was mistaken, because a claim like this
is worth more when it can be checked.

## Tooling

Anthropic's Claude, through Claude Code, over a series of sessions. There is no
generated-code provenance metadata beyond the git history: commits are authored
by the human and carry a `Co-Authored-By` trailer naming the model.

## What has actually been verified

- **556 automated tests**, none of which touch the network. They cover the
  parsing, the model, obfuscation, override handling, support-file reading, the
  renderers and several security properties directly.
- **Continuous integration** on every push and pull request, plus a repository
  hygiene job that fails if a snapshot, render or vendored font is ever
  committed.
- **Behaviour against a real network.** Every feature here, except the gaps
  listed below, was exercised against
  a live UniFi console and, where relevant, a real support file. Claims in the
  documentation that carry numbers were measured rather than estimated.
- **Regular independent review**, by several AI systems, none of them the
  assistant that wrote the code. Security audits, documentation reviews, code
  reviews and architectural reviews, more than one of each and by more than one
  system. They run against the source whenever a substantial change lands
  rather than once at some milestone, so a count here would be out of date by
  the time you read it, and keeping one accurate was its own small chore.

  Everything raised is fixed except one item declined with its reason recorded
  in `CLAUDE.md`: no hashed dependency lock file. One other was declined at
  the time and then done anyway, once the reasoning behind the refusal turned
  out to be weaker than it sounded: the support-file size caps, which became
  adjustable instead.

  **The pattern across them is the useful result, not any single review.** Each
  one found something every previous reviewer had missed, and they were not
  minor: a crafted support file could substitute its own topology data, because
  archive members were matched on a trailing path fragment. A support archive
  could force unbounded decompression, because a skipped member still costs its
  uncompressed size and no cap measured it. An existing output directory was
  silently tightened to 0700, locking out anyone else, in code whose own comment
  said it must not do that.

  Every competent pass so far has still found something, the most recent ones
  included. That is worth weighing against any single review, including the ones
  above and this document.

## What has not been verified

- **No line-by-line human code review.** The human read a great deal of it,
  directed its shape, and rejected plenty, but nobody has audited every line.
- **No professional security assessment.** The reviews above were thorough and
  useful; neither was a penetration test, and neither was performed by a human
  specialist.
- **One controller, one site.** UniFi Network 10.5.67 on a UDM Pro Max, single
  site. Multi-site handling exists and is largely untested.

## How the AI actually failed here, since that is the useful part

Two categories showed up repeatedly, and only one of them is visible in the
result.

**Confidently wrong, then corrected.** Concluding data did not exist after one
failed search, four separate times, each wrong. Writing a summary that
overstated a feature by a factor of three while the correct measurement was
already to hand. Violating an invariant the project had already stated, because
the violation was locally convenient. These leave traces: a correction, a diff,
usually a test.

**Solutions never reached, supplied by the human.** This one leaves no trace at
all, which is why it is worth naming.

Support-file members were capped at 256 MiB. The assistant reasoned itself into
a binary: leave the cap uselessly high, or lower it and risk refusing a
legitimately large network. The human said: make it tunable with sane defaults.
That is an ordinary engineering move. Once implemented it looks like the obvious
design. No bug was filed, no correction appears in any diff, and nothing in the
repository would tell you it happened.

The same shape recurs throughout: a guard that only refuses files the tool did
not write, rather than demanding a flag on every run; a redirect that strips the
credential rather than being refused outright. In each case the assistant had
framed a choice between two bad options and the human declined the frame.

If you are evaluating AI-written code generally, that second category is the one
to think about. The failures that get caught and fixed are visible in the
history. The ceiling on quality when nobody is asking better questions is not.

## What to do with this

Read `src/unifi_map/client.py`. It is the only module that talks to your
controller, it is short, and it makes ten GET requests and nothing else. If you
are going to trust one claim here without checking, do not make it that one.

`SECURITY.md` covers the credential model, what the tool discloses to Ubiquiti's
CDN, and why a support file should be treated as a secret.

Then decide. The honest summary is that this works well, is more carefully built
than a script, has real tests and a real audit behind it, and has not been
line-by-line reviewed by a human. Use it or don't, your call.
