"""Tests for server-owned demo identity context."""

import pytest

from auth import authenticate


def test_vendor_x_demo_identity_has_trusted_attributes():
    identity = authenticate("vendor-x-analyst", "arbiter-demo", "Vendor X")
    assert identity.vendor == "Vendor X"
    assert identity.region == "India"
    assert identity.department == "Analytics"
    assert identity.role == "Analyst"


def test_demo_identity_rejects_vendor_mismatch():
    with pytest.raises(Exception):
        authenticate("vendor-x-analyst", "arbiter-demo", "Vendor A")
