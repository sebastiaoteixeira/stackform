from rest_framework import serializers


class PostsCreatePayload(serializers.Serializer):
    title = serializers.CharField()
    content = serializers.CharField(required=False, allow_null=True)
    authorId = serializers.CharField(required=False, allow_null=True)

class PostsUpdatePayload(serializers.Serializer):
    title = serializers.CharField(required=False, allow_null=True)
    content = serializers.CharField(required=False, allow_null=True)
    authorId = serializers.CharField(required=False, allow_null=True)

class PostsReplacePayload(serializers.Serializer):
    title = serializers.CharField()
    content = serializers.CharField(required=False, allow_null=True)
    authorId = serializers.CharField(required=False, allow_null=True)
