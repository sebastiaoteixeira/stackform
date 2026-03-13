ROUTES = [
    {
        "path": "/users",
        "methods": ["GET", "POST"],
        "operations": {
            "GET": "list",
            "POST": "create",
        },
    },
    {
        "path": "/users/{id}",
        "methods": ["GET", "PATCH", "PUT", "DELETE"],
        "operations": {
            "GET": "get",
            "PATCH": "patch",
            "PUT": "replace",
            "DELETE": "delete",
        },
    },
]
