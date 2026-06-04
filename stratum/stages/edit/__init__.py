"""Edit stage package.

Edit is implemented as a package of deterministic planning, rendering, repair,
and policy modules plus the `edit.py` CLI entrypoint. Internal imports should
prefer package-relative paths so the stage can be reused without relying on
directory-level `sys.path` mutation.
"""
