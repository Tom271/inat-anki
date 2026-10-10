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


SHAREABLE = ["cc0", "cc-by", "cc-by-sa"]
NOT_SHAREABLE = ["cc-by-nc", "cc-by-nc-sa", "cc-by-nd", "cc-by-nc-nd", None, "", "weird"]


@pytest.mark.parametrize("code", SHAREABLE)
def test_shareable_policy_accepts(code):
    assert is_usable(photo(code), "someone_else", "me", policy="shareable")


@pytest.mark.parametrize("code", NOT_SHAREABLE)
def test_shareable_policy_rejects_nc_nd_and_reserved(code):
    assert not is_usable(photo(code), "someone_else", "me", policy="shareable")


@pytest.mark.parametrize("code", NOT_SHAREABLE)
def test_owner_override_applies_to_shareable(code):
    assert is_usable(photo(code), "me", "me", policy="shareable")


def test_empty_user_login_never_matches():
    assert not is_usable(photo(None), "", "", policy="shareable")


def test_unknown_policy_rejected():
    with pytest.raises(ValueError):
        is_usable(photo("cc0"), "a", "b", policy="commercial")


@pytest.mark.parametrize("code", ALLOWED)
def test_every_cc_code_has_a_deed(code):
    from inat_anki.licensing import license_url

    assert license_url(code).startswith("https://creativecommons.org/")
