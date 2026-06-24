"""DRF-specific settings field aggregation.

Extends the shared aggregator with Django-native fields (DJANGO_SECRET_KEY,
DJANGO_DEBUG, DJANGO_ALLOWED_HOSTS) that live only in the DRF output and must
not bleed into the shared build_settings_fields path.
"""

from yaml_api_generator.generators.backend.builders.settings_builder import build_settings_fields
from yaml_api_generator.generators.backend.compile_context import CompileContext, SettingField


def build_drf_settings_fields(ctx: CompileContext) -> list[SettingField]:
    """Return settings fields for the DRF backend.

    Django-native fields are prepended so they appear at the top of the
    generated Settings class, clearly separated from app-level fields.
    """
    django_fields: list[SettingField] = [
        # Required; no default forces explicit configuration in every environment.
        SettingField("DJANGO_SECRET_KEY", "str", None, secret=True),
        SettingField("DJANGO_DEBUG", "str", "false"),
        SettingField("DJANGO_ALLOWED_HOSTS", "str", "*"),
    ]
    return django_fields + build_settings_fields(ctx)
