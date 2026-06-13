from aiogram import Router

from . import analytics, investors, pnl, settings, start


def get_main_router() -> Router:
    """Собирает все роутеры в один корневой.

    Порядок важен: start идёт первым (глобальная кнопка «Главное меню» и
    восстановление состояния после перезапуска), фолбэк-восстановление —
    внутри start и срабатывает только при пустом состоянии.
    """
    router = Router()
    router.include_router(start.router)
    router.include_router(investors.router)
    router.include_router(analytics.router)
    router.include_router(pnl.router)
    router.include_router(settings.router)
    return router
