from yaml_api_generator.runtime.context import RequestContext


async def publish(ctx: RequestContext) -> RequestContext:
    """Set a post's published flag to true."""
    post_id = ctx.url_params.get("id")
    if post_id is None:
        raise ValueError("Missing post id")

    result = await ctx.repository.update(
        "posts", post_id, {"published": True}
    )
    ctx.response = result
    return ctx
