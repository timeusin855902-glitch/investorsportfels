from aiogram.fsm.state import State, StatesGroup


class AddInvestorSG(StatesGroup):
    waiting_name = State()


class AddAssetSG(StatesGroup):
    waiting_ticker = State()
    waiting_amount = State()


class EditAssetSG(StatesGroup):
    waiting_amount = State()


class SettingsReportSG(StatesGroup):
    waiting_time = State()


class SettingsVolatilitySG(StatesGroup):
    waiting_threshold = State()
