"""Point-in-time feature datasets and robust conditional-edge discovery."""

from .dataset import EdgeRow, build_edge_rows, flatten_features
from .outcomes import SignalPathOutcome, evaluate_signal_path
from .persistence import persist_feature_snapshot, persist_signal_outcome
from .discovery import CandidateEdge, discover_univariate_edges, temporal_holdout

__all__ = [
    "CandidateEdge",
    "EdgeRow",
    "SignalPathOutcome",
    "build_edge_rows",
    "discover_univariate_edges",
    "evaluate_signal_path",
    "flatten_features",
    "persist_feature_snapshot",
    "persist_signal_outcome",
    "temporal_holdout",
]
