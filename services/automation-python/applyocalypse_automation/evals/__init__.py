"""Offline evaluation of the generated-text stages.

The graders here answer the question the style validator cannot: is this text
*true*? A cover letter that names an employer the candidate never worked for,
or claims a number that appears nowhere in their history, is a lie sent under
the user's name. That is the failure mode worth gating a release on.
"""

from .graders import (
    GraderResult,
    grade_groundedness,
    grade_mentions,
    grade_style,
    grade_text,
)

__all__ = [
    "GraderResult",
    "grade_groundedness",
    "grade_mentions",
    "grade_style",
    "grade_text",
]
