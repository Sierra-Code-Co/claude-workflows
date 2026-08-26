"""Absolute-path entrypoint, so the working directory is never on sys.path.

`python -m review_plan_v2` puts the CURRENT WORKING DIRECTORY at `sys.path[0]`,
ahead of everything PYTHONPATH contributes. The wrapper runs inside the
repository under review and does not `cd` anywhere, so cwd is normally that
repository's root — untrusted content by definition, since reviewing it is the
whole job. A branch carrying `review_plan_v2/__init__.py` at its root would
therefore be imported INSTEAD of the real package, with every provider API key
already exported into the environment by the wrapper. Arbitrary code execution
with the credentials attached, triggered by nothing more than running a review.

Running a FILE by absolute path is the one invocation mode that does not do
this: `sys.path[0]` becomes the script's own directory, which is where the real
package lives. `-P` / `PYTHONSAFEPATH` would also close it but only from 3.11,
and the declared floor is 3.10 (`check_deps.MIN_PYTHON`), so on the floor
version itself the guard would silently not apply — a fix that is absent exactly
where the version matrix is widest.

This file is deliberately 3.9-parseable, with no annotations and no imports
beyond the stdlib. `python3 -m review_plan_v2` on a below-floor interpreter
prints check_deps' refusal and exits 2; if the shim in front of it failed to
parse first, that refusal would be replaced by a SyntaxError and the floor guard
would be the thing reporting the floor problem incorrectly.

`python3 -m review_plan_v2` remains supported and is still what CI, the
Dockerfile, and the README use. Those run in a trusted checkout with a known
cwd; the wrapper is the one caller whose cwd is chosen by the material under
review.
"""
import os
import sys

if __name__ == "__main__":
    # Belt and braces. sys.path[0] is already this file's directory by virtue of
    # being run as a file, but an ambient PYTHONPATH entry earlier in the list
    # could still shadow the package, and the wrapper prepends SCRIPT_DIR to
    # whatever PYTHONPATH the caller had rather than replacing it.
    # realpath, not abspath: abspath does not resolve symlinks, so this file reached
    # through a link into a bin directory would add the LINK's directory and fail to
    # import the package beside the real file. The shell wrapper already readlinks
    # its own $0 for exactly this reason; the two entrypoints should not disagree
    # about what "this file's directory" means.
    _here = os.path.dirname(os.path.realpath(__file__))
    sys.path.insert(0, _here)

    from review_plan_v2.__main__ import main

    sys.exit(main())
