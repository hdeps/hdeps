# hdeps

Simple dependency not-a-solver lets you debug where backtracking would happen,
or figure out what would change on a platform that's not the same as you're
running right now.

This code was originally part of [honesty](https://pypi.org/project/honesty/)
but is easier to iterate on with pypi-simple as its source.

```sh
$ hdeps requests
...
$ hdeps --install-order requests
...
$ hdeps --have urllib3==1.999 requests
...
```

# Why isn't it a solver?

Think of this as a debugging solver.  It doesn't come up with one single
solution, but does the bulk of the legwork to let you, the human, figure out
what the problematic part of your dep tree is (even if the machine you're
running on isn't the same as you're trying to figure out).

If you want a real solver, I highly recommend look at
[resolvelib](https://pypi.org/project/resolvelib/) for low-level operations, or
[poetry](https://pypi.org/project/poetry/) which includes a higher-level solver
that keeps track of operations (like "upgrade" separately from "install").

# Version Compat

This project should work on 3.10-3.12, including mypy compatibility as checked
by tests.  Linting on older versions will not catch all issues (e.g. whitespace
in f-strings), so 3.12 is recommended.  Some transitive dependencies
(pydantic-core and libcst) rely on binary wheels that are not available yet on
3.13 and do not easily build from source.

# License

MIT, see `LICENSE` for details.
