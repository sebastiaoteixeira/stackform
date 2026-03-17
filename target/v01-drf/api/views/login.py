from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from api.authentication.auth import verify_password
from api.authentication.jwt_utils import create_jwt_token
from api.authentication.mongodb import get_database


class UsersLoginView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        identifier_value = request.data.get("email")
        password = request.data.get("password")

        if not identifier_value or not password:
            return Response(
                {"detail": "Invalid credentials"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        db = get_database()
        col = db["users"]
        for doc in col.find({}):
            if str(doc.get("email", "")) != str(identifier_value):
                continue
            stored_hash = doc.get("passwordHash")
            if not isinstance(stored_hash, str):
                continue
            if not verify_password(str(password), stored_hash):
                continue

            subject = doc.get("id")
            if subject is None:
                continue

            token = create_jwt_token(str(subject), "users")
            safe_user = {
                k: v for k, v in doc.items()
                if k not in ("password", "passwordHash", "_id")
            }
            return Response({"token": token, "user": safe_user})

        return Response(
            {"detail": "Invalid credentials"},
            status=status.HTTP_401_UNAUTHORIZED,
        )

