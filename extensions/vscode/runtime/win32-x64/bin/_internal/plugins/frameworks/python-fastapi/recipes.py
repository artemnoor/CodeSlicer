"""FastAPI semantic recipes owned by the FastAPI framework pack."""
from semantic_binding.models import Recipe


def semantic_recipes() -> list[Recipe]:
    return [
        Recipe(
            id="plugin.fastapi.router_object_flow",
            type="object_graph",
            constructor="APIRouter",
            prefix_kwarg="prefix",
            include_method="include_router",
            decorator_methods=["delete", "get", "head", "options", "patch", "post", "put"],
        )
    ]
