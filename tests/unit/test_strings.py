"""Tests for string manipulation utilities."""

import pytest

from yaml_api_generator.utils.strings import to_pascal_case


class TestToPascalCase:
    """Tests for to_pascal_case function."""

    def test_snake_case(self):
        """Convert snake_case to PascalCase."""
        assert to_pascal_case("user_profile") == "UserProfile"
        assert to_pascal_case("api_key") == "ApiKey"
        assert to_pascal_case("user_profile_settings") == "UserProfileSettings"

    def test_camel_case(self):
        """Convert camelCase to PascalCase."""
        assert to_pascal_case("userProfile") == "UserProfile"
        assert to_pascal_case("apiKey") == "ApiKey"
        assert to_pascal_case("userProfileSettings") == "UserProfileSettings"

    def test_kebab_case(self):
        """Convert kebab-case to PascalCase."""
        assert to_pascal_case("user-profile") == "UserProfile"
        assert to_pascal_case("api-key") == "ApiKey"
        assert to_pascal_case("user-profile-settings") == "UserProfileSettings"

    def test_pascal_case(self):
        """PascalCase input should remain unchanged."""
        assert to_pascal_case("UserProfile") == "UserProfile"
        assert to_pascal_case("ApiKey") == "ApiKey"
        assert to_pascal_case("UserProfileSettings") == "UserProfileSettings"

    def test_single_word(self):
        """Single word should be capitalized."""
        assert to_pascal_case("user") == "User"
        assert to_pascal_case("api") == "Api"
        assert to_pascal_case("profile") == "Profile"

    def test_mixed_formats(self):
        """Handle mixed naming conventions."""
        assert to_pascal_case("user_Profile") == "UserProfile"
        assert to_pascal_case("API_key") == "ApiKey"
        assert to_pascal_case("user-profileSettings") == "UserProfileSettings"

    def test_edge_cases(self):
        """Handle edge cases."""
        assert to_pascal_case("") == ""
        assert to_pascal_case("a") == "A"
        assert to_pascal_case("_") == ""
        assert to_pascal_case("-") == ""
        assert to_pascal_case("__") == ""
        assert to_pascal_case("user__profile") == "UserProfile"
        assert to_pascal_case("user--profile") == "UserProfile"

    def test_numbers(self):
        """Handle names with numbers."""
        assert to_pascal_case("user_2fa") == "User2fa"
        assert to_pascal_case("api_v2") == "ApiV2"
        assert to_pascal_case("user2Profile") == "User2Profile"