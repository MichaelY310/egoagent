"""Optional Flow Relay experiment.

This package deliberately depends on EgoAgent's public project/session
projection; the runtime never depends on this package.  Removing the package
and its marked frontend registration leaves Project Portfolio untouched.
"""

from .service import FlowRelayService

__all__ = ["FlowRelayService"]
