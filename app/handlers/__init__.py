from aiogram import Router

from . import analytics, investors, settings, start


def get_main_router() -> Router:
    """Собирает все роутеры в один корневой."""
    router = Router()
    router.include_router(start.router)
    router.include_router(investors.router)
    router.include_router(analytics.router)
    router.include_router(settings.router)
    return router
