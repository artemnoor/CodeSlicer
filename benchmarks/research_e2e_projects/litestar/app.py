from litestar import Litestar, get
from litestar.di import Provide

def provide_repo():
    return object()

@get('/orders', dependencies={'repo': Provide(provide_repo)})
def list_orders(repo):
    return {'ok': True}

app = Litestar(route_handlers=[list_orders])
