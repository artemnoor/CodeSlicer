"""Review projection package: bounded, ranked, evidence-first output."""
from .contracts import ReviewCandidate, ReviewChain, ReviewEvidence, ReviewProjection, ReviewRank, TestRecommendation
from .projector import build_review_projection

__all__ = [
    "ReviewCandidate", "ReviewChain", "ReviewEvidence", "ReviewProjection", "ReviewRank",
    "TestRecommendation", "build_review_projection",
]
