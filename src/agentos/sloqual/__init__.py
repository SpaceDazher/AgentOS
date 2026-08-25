"""AgentOS SLO qualification harness (ticket SLOQUAL-001, extends S1-002).

Package-level tooling only: never imported by core runtime paths, stdlib-only,
and versioned via ``RUNNER_VERSION`` which is stamped into every result file
and enforced by the fail-closed comparator.
"""
from .environment import RUNNER_VERSION

__all__ = ["RUNNER_VERSION"]
