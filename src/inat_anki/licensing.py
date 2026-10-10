"""Photo licence policy (SPEC 8). Pure: no I/O."""

from inat_anki.model import Photo

# Usable for personal, non-commercial study with attribution shown on the card. Putting a
# resized photo unchanged on a card is reproduction, not adaptation, so ND is acceptable.
LICENSE_LABELS = {
    "cc0": "CC0",
    "cc-by": "CC BY",
    "cc-by-sa": "CC BY-SA",
    "cc-by-nc": "CC BY-NC",
    "cc-by-nc-sa": "CC BY-NC-SA",
    "cc-by-nd": "CC BY-ND",
    "cc-by-nc-nd": "CC BY-NC-ND",
}
ALL_RIGHTS_RESERVED = "All rights reserved"

# Policies (SPEC-v2 6.3). "personal" is for private study; "shareable" is for decks that
# may be shared publicly: no NC (non-commercial) and no ND (no-derivatives) licences.
POLICIES = {
    "personal": frozenset(LICENSE_LABELS),
    "shareable": frozenset({"cc0", "cc-by", "cc-by-sa"}),
}

# Licence deeds. iNat codes carry no version; iNat applies the 4.0 licences.
LICENSE_URLS = {
    "cc0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "cc-by": "https://creativecommons.org/licenses/by/4.0/",
    "cc-by-sa": "https://creativecommons.org/licenses/by-sa/4.0/",
    "cc-by-nc": "https://creativecommons.org/licenses/by-nc/4.0/",
    "cc-by-nc-sa": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
    "cc-by-nd": "https://creativecommons.org/licenses/by-nd/4.0/",
    "cc-by-nc-nd": "https://creativecommons.org/licenses/by-nc-nd/4.0/",
}


def is_usable(photo: Photo, observer_login: str, user_login: str, policy: str = "personal") -> bool:
    if policy not in POLICIES:
        raise ValueError(f"unknown licence policy {policy!r}")
    if user_login and observer_login.lower() == user_login.lower():
        return True
    return (photo.license_code or "").lower() in POLICIES[policy]


def license_url(code: str | None) -> str | None:
    return LICENSE_URLS.get((code or "").lower())


def license_label(code: str | None) -> str:
    if code is None:
        return ALL_RIGHTS_RESERVED
    return LICENSE_LABELS.get(code.lower(), code)
