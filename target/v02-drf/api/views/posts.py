from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema
from api.serializers.posts import PostsCreatePayload, PostsUpdatePayload
from api.repositories.posts import PostsRepository
from api.services.posts import PostsService
from api.services.exceptions import NotFoundError, ValidationError
from api.authentication.mongodb import get_database
from api.authentication.auth import resolve_principal




class PostsListView(APIView):

    @extend_schema()

    def get(self, request):
        db = get_database()
        repo = PostsRepository(db)
        service = PostsService(repo)

        try:
            documents = service.list()
            return Response(documents)
        except NotFoundError:
            return Response({"detail": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        except ValidationError as exc:
            return Response({"detail": exc.message}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

    @extend_schema()

    def post(self, request):
        db = get_database()
        repo = PostsRepository(db)
        service = PostsService(repo)

        try:
            serializer = PostsCreatePayload(data=request.data)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data
            document = service.create(data)
            return Response(document, status=status.HTTP_201_CREATED)
        except NotFoundError:
            return Response({"detail": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        except ValidationError as exc:
            return Response({"detail": exc.message}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

    @extend_schema()

    def get(self, request):
        db = get_database()
        repo = PostsRepository(db)
        service = PostsService(repo)
        db = get_database()
        principal = resolve_principal(request, db)
        if principal is None:
            return Response({"detail": "Unauthorized"}, status=status.HTTP_401_UNAUTHORIZED)

        try:
        except NotFoundError:
            return Response({"detail": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        except ValidationError as exc:
            return Response({"detail": exc.message}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

class PostsDetailView(APIView):

    @extend_schema()

    def get(self, request, pk):
        db = get_database()
        repo = PostsRepository(db)
        service = PostsService(repo)

        try:
            document = service.get(pk)
            return Response(document)
        except NotFoundError:
            return Response({"detail": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        except ValidationError as exc:
            return Response({"detail": exc.message}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

    @extend_schema()

    def patch(self, request, pk):
        db = get_database()
        repo = PostsRepository(db)
        service = PostsService(repo)
        db = get_database()
        principal = resolve_principal(request, db)
        if principal is None:
            return Response({"detail": "Unauthorized"}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            serializer = PostsUpdatePayload(data=request.data)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data
            document = service.update(pk, data)
            return Response(document)
        except NotFoundError:
            return Response({"detail": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        except ValidationError as exc:
            return Response({"detail": exc.message}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

    @extend_schema()

    def delete(self, request, pk):
        db = get_database()
        repo = PostsRepository(db)
        service = PostsService(repo)
        db = get_database()
        principal = resolve_principal(request, db)
        if principal is None:
            return Response({"detail": "Unauthorized"}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            document = service.delete(pk)
            return Response(document)
        except NotFoundError:
            return Response({"detail": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        except ValidationError as exc:
            return Response({"detail": exc.message}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
