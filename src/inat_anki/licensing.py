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


def is_usable(photo: Photo, observer_login: str, user_login: str) -> bool:
    if observer_login.lower() == user_login.lower():
        return True
    return (photo.license_code or "").lower() in LICENSE_LABELS


def license_label(code: str | None) -> str:
    if code is None:
        return ALL_RIGHTS_RESERVED
    return LICENSE_LABELS.get(code.lower(), code)
