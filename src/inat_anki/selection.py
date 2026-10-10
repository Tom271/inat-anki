"""Choose licensed photos for species cards (SPEC-v2 6.1). Pure: no I/O."""

from collections.abc import Iterable, Mapping
from html import escape

from inat_anki.licensing import is_usable, license_label, license_url
from inat_anki.model import ChosenPhoto, Observation, Photo
from inat_anki.normalise import media_filename, photo_url
from inat_anki.render import OBS_URL


def photo_key(photo: Photo) -> str:
    return f"inat:{photo.id}"


def inat_credit(photo: Photo, obs: Observation) -> str:
    """Attribution, licence linked to its deed, and a link to the source observation."""
    label = license_label(photo.license_code)
    url = license_url(photo.license_code)
    licence = f'<a href="{url}">{escape(label)}</a>' if url else escape(label)
    who = escape(photo.attribution.strip() or obs.user_login)
    return f'{who} · {licence} · <a href="{OBS_URL.format(id=obs.id)}">iNaturalist</a>'


def to_chosen(photo: Photo, obs: Observation, size: str) -> ChosenPhoto:
    return ChosenPhoto(
        key=photo_key(photo),
        filename=media_filename(photo),
        url=photo_url(photo, size),
        credit_html=inat_credit(photo, obs),
        source_id=str(obs.id),
        license=photo.license_code or "",
    )


def usable_photos(obs: Observation, policy: str, user_login: str) -> list[Photo]:
    return [p for p in obs.photos if is_usable(p, obs.user_login, user_login, policy)]


def choose_photos(
    candidates: Iterable[Observation],
    n: int,
    policy: str,
    user_login: str,
    size: str,
    previous: Iterable[str] = (),
    previous_obs: Mapping[str, Observation] | None = None,
) -> list[ChosenPhoto]:
    """Up to `n` photos, each from a different observation, preferring different observers.

    Earlier choices are kept (SPEC-v2 6.1 rule 4) while their photo is still present and
    usable in `previous_obs` (fresh API data for the observations chosen before, keyed by
    observation ID as a string). They are listed in `previous` as ChosenPhoto keys.
    """
    chosen: list[tuple[ChosenPhoto, str]] = []  # with observer login
    used_obs: set[str] = set()

    previous_obs = previous_obs or {}
    for key in previous:
        for obs in previous_obs.values():
            photo = next(
                (p for p in usable_photos(obs, policy, user_login) if photo_key(p) == key), None
            )
            if photo and str(obs.id) not in used_obs:
                chosen.append((to_chosen(photo, obs, size), obs.user_login))
                used_obs.add(str(obs.id))
                break
        if len(chosen) == n:
            return [c for c, _ in chosen]

    candidates = [o for o in candidates if str(o.id) not in used_obs]
    for allow_same_observer in (False, True):
        for obs in candidates:
            if len(chosen) == n:
                break
            if str(obs.id) in used_obs:
                continue
            if not allow_same_observer and obs.user_login in {who for _, who in chosen}:
                continue
            photos = usable_photos(obs, policy, user_login)
            if photos:
                chosen.append((to_chosen(photos[0], obs, size), obs.user_login))
                used_obs.add(str(obs.id))
    return [c for c, _ in chosen]
