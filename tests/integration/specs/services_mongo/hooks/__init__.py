async def echo(request):
    return {
        "params": request.params,
        "query": request.query,
        "body": request.body,
        "principal": request.principal and {"sub": request.principal["sub"]},
        "inputs": request.inputs,
    }
