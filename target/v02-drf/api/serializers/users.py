from rest_framework import serializers


class UsersCreatePayload(serializers.Serializer):
    email = serializers.CharField()
    displayName = serializers.CharField()
    role = serializers.ChoiceField(required=False, default='user', choices=["admin", "moderator", "user"])
    password = serializers.CharField(min_length=1)

class UsersUpdatePayload(serializers.Serializer):
    email = serializers.CharField(required=False, allow_null=True)
    displayName = serializers.CharField(required=False, allow_null=True)
    role = serializers.ChoiceField(required=False, allow_null=True, default='user', choices=["admin", "moderator", "user"])
