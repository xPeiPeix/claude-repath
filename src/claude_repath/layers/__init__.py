"""Migration layers — each module handles one kind of state.

Every layer module exposes two functions:

* ``plan(ctx) -> list[str]`` — describe what would change (no mutation)
* ``apply(ctx, session) -> list[str]`` — back up, then mutate; returns what changed
"""
