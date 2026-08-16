"""Amosclaud CI-time tooling.

Deliberately empty. Modules here run in the leanest environments the project
has -- the fast pull-request lane and release images -- so this package must
never import anything on the way in. Adding an import to this file would
recreate the class of failure that ``import_reachability`` exists to catch.
"""
