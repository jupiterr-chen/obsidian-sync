"""Knowledge layer for the research KB (P1+).

Independent storage, immutable content-addressed snapshots and idempotent
stage jobs on top of the first-layer library catalog. Never writes to the
library catalog database; consumes it through a read-only connection.

See docs/adr/0003-knowledge-layer-storage.md for the design decisions.
"""

__version__ = "0.1.0"
