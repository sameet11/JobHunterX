"""Returns the right applier instance for a given platform name."""

from __future__ import annotations

from config.user_config import UserConfig
from src.apply.base_applier import BaseApplier
from src.apply.naukri_applier import NaukriApplier

_REGISTRY: dict[str, type[BaseApplier]] = {
    "naukri": NaukriApplier,
}


def get_applier(platform_name: str, user_config: UserConfig) -> BaseApplier:
    key = platform_name.lower()
    if key not in _REGISTRY:
        raise ValueError(
            f"No applier for platform: {platform_name}. Known: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[key](user_config)
