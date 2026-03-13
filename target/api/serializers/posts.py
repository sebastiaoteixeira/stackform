from rest_framework import serializers


class PostsCreatePayload(serializers.Serializer):
    title = serializers.CharField(min_length=3)
    content = serializers.CharField()
    tags = serializers.ListField(required=False, allow_null=True, child=serializers.CharField())
    publishedAt = serializers.DateTimeField(required=False, allow_null=True)
    authorId = serializers.CharField(required=False, allow_null=True)

class PostsUpdatePayload(serializers.Serializer):
    title = serializers.CharField(required=False, allow_null=True, min_length=3)
    content = serializers.CharField(required=False, allow_null=True)
    tags = serializers.ListField(required=False, allow_null=True, child=serializers.CharField())
    publishedAt = serializers.DateTimeField(required=False, allow_null=True)
    authorId = serializers.CharField(required=False, allow_null=True)
