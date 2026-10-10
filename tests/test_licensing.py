import pytest

from inat_anki.licensing import is_usable, license_label
from inat_anki.model import Photo

ALLOWED = ["cc0", "cc-by", "cc-by-sa", "cc-by-nc", "cc-by-nc-sa", "cc-by-nd", "cc-by-nc-nd"]


def photo(code):
    return Photo(1, "https://x/photos/1/square.jpg", code, "")


@pytest.mark.parametrize("code", ALLOWED)
def test_cc_licences_allowed_for_others(code):
    assert is_usable(photo(code), "someone_else", "me")


@pytest.mark.parametrize("code", ["CC-BY", "Cc-By-Nc"])
def test_codes_are_case_insensitive(code):
    assert is_usable(photo(code), "someone_else", "me")


@pytest.mark.parametrize("code", [None, "", "gfdl", "cc-by-4.0", "unknown"])
def test_reserved_and_unknown_excluded_for_others(code):
    assert not is_usable(photo(code), "someone_else", "me")


@pytest.mark.parametrize("code", [None, "unknown", *ALLOWED])
def test_owner_always_allowed(code):
    assert is_usable(photo(code), "Me", "me")


@pytest.mark.parametrize(
    ("code", "label"),
    [
        ("cc0", "CC0"),
        ("cc-by", "CC BY"),
        ("cc-by-sa", "CC BY-SA"),
        ("cc-by-nc", "CC BY-NC"),
        ("cc-by-nc-sa", "CC BY-NC-SA"),
        ("cc-by-nd", "CC BY-ND"),
        ("cc-by-nc-nd", "CC BY-NC-ND"),
        (None, "All rights reserved"),
        ("weird", "weird"),
    ],
)
def test_license_label(code, label):
    assert license_label(code) == label
