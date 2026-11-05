#!/usr/bin/env python3
"""Resolve the check steps of a rosa-gap-analysis ci-operator workflow.

Reads a workflow YAML, expands the chain(s) in its ``test`` phase, and for each
ref opens that ref's YAML to find the ``commands:`` script. Prints one line per
check ref, in workflow order:

    <ref-as>\t<absolute-path-to-commands-script>

``gap-all.sh`` consumes this so the chain and ref YAML — not a hardcoded list —
decide which checks run and in what order. The checks live in the
``rosa-gap-analysis-checks`` chain, which may sit in any phase (it is in ``post``
so every check runs even after one fails). This expands the chain(s) wherever
they appear and skips the standalone lifecycle refs (setup, ocm-auth,
resolve-versions, report, cleanup), which gap-all.sh handles itself.
"""

import argparse
import glob
import os
import sys

import yaml


def _load(path):
    with open(path) as handle:
        return yaml.safe_load(handle) or {}


def build_index(registry):
    """Map ``as`` -> info for every ref and chain under the registry.

    Refs map to the absolute path of their ``commands:`` script; chains map to
    their ordered list of step entries.
    """
    refs = {}
    for path in glob.glob(os.path.join(registry, "*", "*-ref.yaml")):
        data = _load(path).get("ref") or {}
        name = data.get("as")
        commands = data.get("commands")
        if name and commands:
            refs[name] = os.path.join(os.path.dirname(path), commands)

    chains = {}
    for path in glob.glob(os.path.join(registry, "*", "*-chain.yaml")):
        data = _load(path).get("chain") or {}
        name = data.get("as")
        if name:
            chains[name] = data.get("steps") or []

    return refs, chains


def expand(entries, chains, seen=None):
    """Yield ref names in order, expanding nested chains."""
    if seen is None:
        seen = set()
    for entry in entries or []:
        if "ref" in entry:
            yield entry["ref"]
        elif "chain" in entry:
            name = entry["chain"]
            if name in seen:
                raise SystemExit(f"ERROR: chain cycle detected at {name}")
            if name not in chains:
                raise SystemExit(f"ERROR: chain not found in registry: {name}")
            yield from expand(chains[name], chains, seen | {name})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workflow", help="Path to the workflow YAML")
    parser.add_argument(
        "--registry",
        help="Step-registry root (default: two levels up from the workflow file)",
    )
    args = parser.parse_args()

    registry = args.registry or os.path.dirname(
        os.path.dirname(os.path.abspath(args.workflow))
    )

    workflow = _load(args.workflow).get("workflow") or {}
    steps = workflow.get("steps") or {}

    # Checks live in a chain (lifecycle steps are standalone refs). Expand the
    # chain(s) wherever they appear across phases; skip standalone refs.
    chain_entries = []
    for phase in ("pre", "test", "post"):
        chain_entries.extend(e for e in (steps.get(phase) or []) if "chain" in e)

    refs, chains = build_index(registry)

    count = 0
    for ref in expand(chain_entries, chains):
        cmd = refs.get(ref)
        if not cmd:
            raise SystemExit(f"ERROR: ref not found or missing commands: {ref}")
        print(f"{ref}\t{cmd}")
        count += 1

    if count == 0:
        print(f"ERROR: no check refs resolved from {args.workflow}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
