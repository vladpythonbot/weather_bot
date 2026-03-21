from aiogram.fsm.state import State,StatesGroup

class City(StatesGroup):
    name = State()