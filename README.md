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


# Version Compat

This library works only on 3.10-3.12, and linting requires 3.12 for full
fidelity.  I do not yet know how well it works on 3.13 because I haven't gotten
pydantic-core to compile there and they don't provide a wheel.

# License

hdeps is copyright [Tim Hatch](https://timhatch.com/), and licensed under
the MIT license.  I am providing code in this repository to you under an open
source license.  This is my personal repository; the license you receive to
my code is from me and not from my employer. See the `LICENSE` file for details.
