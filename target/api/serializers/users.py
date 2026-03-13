from rest_framework import serializers


class UsersCreatePayload(serializers.Serializer):
    username = serializers.CharField()
    bio = serializers.CharField(required=False, allow_null=True)
    age = serializers.FloatField(required=False, allow_null=True)

class UsersUpdatePayload(serializers.Serializer):
    username = serializers.CharField(required=False, allow_null=True)
    bio = serializers.CharField(required=False, allow_null=True)
    age = serializers.FloatField(required=False, allow_null=True)
