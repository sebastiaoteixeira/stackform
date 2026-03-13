from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema
from api.serializers.users import UsersCreatePayload, UsersUpdatePayload
from api.repositories.users import UsersRepository
from api.services.users import UsersService
from api.services.exceptions import NotFoundError, ValidationError
from api.authentication.mongodb import get_database




class UsersListView(APIView):

    @extend_schema()

    def get(self, request):
        db = get_database()
        repo = UsersRepository(db)
        service = UsersService(repo)

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
        repo = UsersRepository(db)
        service = UsersService(repo)

        try:
            serializer = UsersCreatePayload(data=request.data)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data
            document = service.create(data)
            return Response(document, status=status.HTTP_201_CREATED)
        except NotFoundError:
            return Response({"detail": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        except ValidationError as exc:
            return Response({"detail": exc.message}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

class UsersDetailView(APIView):

    @extend_schema()

    def get(self, request, pk):
        db = get_database()
        repo = UsersRepository(db)
        service = UsersService(repo)

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
        repo = UsersRepository(db)
        service = UsersService(repo)

        try:
            serializer = UsersUpdatePayload(data=request.data)
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
        repo = UsersRepository(db)
        service = UsersService(repo)

        try:
            document = service.delete(pk)
            return Response(document)
        except NotFoundError:
            return Response({"detail": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        except ValidationError as exc:
            return Response({"detail": exc.message}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
