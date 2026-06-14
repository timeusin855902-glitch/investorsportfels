"""FSM-состояния (экраны и шаги ввода) для навигации на reply-клавиатурах."""
from aiogram.fsm.state import State, StatesGroup


class St(StatesGroup):
    # Экраны-меню
    main = State()          # главное меню
    investors = State()     # список инвесторов
    investor = State()      # карточка инвестора (меню действий)
    analytics = State()     # меню аналитики
    pnl = State()           # раздел «Прибыль/Убыток» (список инвесторов)
    settings = State()      # меню настроек

    # Добавление инвестора
    add_investor = State()

    # Добавление актива (точка входа): тикер → выбор монеты → цена → кол-во → дата
    a_ticker = State()
    a_pick = State()    # выбор конкретной монеты, если тикер неоднозначный
    a_price = State()
    a_amount = State()
    a_date = State()

    # Продажа актива: выбор → цена → количество → дата
    s_pick = State()
    s_price = State()
    s_amount = State()
    s_date = State()

    # Удаление актива и инвестора
    d_pick = State()
    del_investor = State()

    # Настройки
    set_freq = State()
    set_freq_input = State()
    set_threshold = State()
    set_threshold_input = State()
    set_report_threshold = State()
    set_report_threshold_input = State()
    set_admins = State()
    set_admin_add = State()
