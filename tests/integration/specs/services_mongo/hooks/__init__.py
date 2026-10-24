async def echo(request):
    return {
        "params": request.params,
        "query": request.query,
        "body": request.body,
        "principal": request.principal,
        "inputs": request.inputs,
    }
