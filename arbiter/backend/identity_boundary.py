"""Dependency-free guards for the server-owned policy identity boundary."""

from __future__ import annotations

import re
from typing import Optional, Protocol


class VendorIdentity(Protocol):
    """The only identity attribute required by the cross-tenant guard."""

    vendor: str


def identity_override_reason(question: str, identity: VendorIdentity) -> Optional[str]:
    """Return a reason when text tries to change trusted policy identity.

    Policy rulings are tenant-scoped. The authenticated identity must be the
    sole source of the vendor, region, department, and role used for a ruling;
    a model must never be asked to decide whether a message can replace it.
    """
    normalised_question = " ".join(question.casefold().split())
    expected_vendor = " ".join(identity.vendor.casefold().split())

    # A policy question for a different explicitly named vendor is a
    # cross-tenant request, even if it is phrased without an obvious prompt
    # injection instruction (for example, "Can Vendor A receive Dataset Y?").
    for match in re.finditer(r"\bvendor\s+([a-z0-9_-]+)\b", normalised_question):
        requested_vendor = f"vendor {match.group(1)}"
        if requested_vendor != expected_vendor:
            return (
                f"The message requests a ruling for {requested_vendor.title()}, but "
                f"the authenticated vendor is {identity.vendor}."
            )

    # Reject attempts to override any of the remaining server-owned context
    # fields. This runs before retrieval and before any provider is called, so
    # model behavior cannot weaken the boundary.
    override_pattern = (
        r"\b(?:ignore|override|bypass|change|replace|discard)\b[^.?!]{0,80}"
        r"\b(?:identity|context|vendor|region|department|role|permissions?)\b"
    )
    assumed_identity_pattern = (
        r"\b(?:i am|i'm|treat me as|act as|use|apply)\s+"
        r"(?:an?\s+)?(?:vendor\s+[a-z0-9_-]+|india|us|usa|eu|europe|"
        r"analytics|security|finance|engineering)\b"
    )
    if re.search(override_pattern, normalised_question) or re.search(
        assumed_identity_pattern, normalised_question
    ):
        return "The message attempts to change authenticated policy context."
    return None
