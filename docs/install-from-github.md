# Installing from GitHub, without a checkout

[← Documentation index](../README.md#documentation)

This page covers two ways to get `unifi-map` onto a machine with a
single `pip install` command. Neither needs `git clone`, a PyPI account,
or a publishing decision from this project. See
[`TODO.md`](../TODO.md#undecided-rather-than-unstarted) for why
publishing itself is still undecided. This project verified both
methods against a real install, rather than assuming they work.

## From a tag, building at install time

```bash
pip install "git+https://github.com/gitkodak/unifi-map.git@v0.10.0"
```

`pip` clones the repository at that ref, and builds it with the same
`pyproject.toml` [`make build`](../README.md#installing-it-somewhere-else)
uses. So this needs `git` on the installing machine, but nothing else
beyond the usual Python build tooling `pip` already brings.

Pin a released tag, as above. `@main` also works, but tracks whatever is
newest on the default branch, which is the same "not stable yet" caveat the
rest of this project carries pre-1.0.

## From a release asset, no build step

Every tag from 0.10.0 onward has its wheel and sdist attached to the
matching [GitHub Release](https://github.com/gitkodak/unifi-map/releases).
If you install one directly, that skips the build entirely:

```bash
pip install https://github.com/gitkodak/unifi-map/releases/download/v0.10.0/unifi_map-0.10.0-py3-none-any.whl
```

The filename encodes the version, so copy it from the Release page rather
than guessing it. `unifi_map`, with an underscore, is the wheel's own name,
even though the project and the command are both spelled `unifi-map`.

## Either way

Graphviz is still a separate system dependency, exactly as in the main
[Install](../README.md#install) section: a wheel cannot carry `dot` and
`unflatten` along with it.

**`man unifi-map` works after either method**, from 0.10.0 on, once you
activate the virtual environment, with no `MANPATH` to configure. This
project ships the man page as installed data
(`share/man/man1/unifi-map.1`), and both macOS's and GNU man-db's `man`
search a venv's `share/man` automatically, once its `bin` directory is
on `PATH`. Earlier versions don't carry this. Use `man ./unifi-map.1`
from a checkout instead.
