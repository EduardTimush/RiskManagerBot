import ccxt
import time
import asyncio
import datetime
from tg_notifications import send_message

import logging
from logging.handlers import RotatingFileHandler

log = logging.getLogger('riskbot')
log.setLevel(logging.INFO)

fmt = logging.Formatter('%(asctime)s | %(levelname)s | %(name)s | %(message)s')

file_handler = RotatingFileHandler('riskbot.log', maxBytes=5_000_000, backupCount=3, encoding='utf-8')
file_handler.setFormatter(fmt)

console = logging.StreamHandler()
console.setFormatter(fmt)

log.addHandler(file_handler)
log.addHandler(console)

API_KEY = ""
SECRET_KEY = ""

MAX_LOSS_USDT = 2
SETTLE = 'usdt'

log.info(f'MAX_LOSS={MAX_LOSS_USDT}')

exchange = ccxt.gate({
    'apiKey':API_KEY,
    'secret':SECRET_KEY,
    'enableRateLimit':True,
    'options':{'defaultType':'swap', 'fetchMarkets':{'types':['swap']}} # fetchMarkets позволяет выбрать тип рынка, чтоб не грузить запрос.
})


def contract_multiplier(contract):
    multiplier = exchange.publicFuturesGetSettleContractsContract({'settle': SETTLE,
                                                                   'contract': 'BTC_USDT'})
    return multiplier['quanto_multiplier']


def opened_positions():
    positions = exchange.privateFuturesGetSettlePositions({'settle': SETTLE, 'holding': True})  # Информация о текущих позициях
    opened_positions = [x['contract'] for x in positions if float(x['size']) != 0]  # Открытые позиции по тикерам
    return opened_positions


def price_limit_orders():
    price_ord = exchange.privateFuturesGetSettlePriceOrders({'settle': SETTLE,
                                                                'status': 'open'})  # Условные ордера, по типу TP/SL
    price_orders = set([x['initial']['contract'] for x in price_ord])

    limit_ord = exchange.privateFuturesGetSettleOrders({'settle': SETTLE,
                                                           'status': 'open'})  # Лимитные ордера
    limit_orders = set([x['contract'] for x in limit_ord])
    return price_orders, limit_orders


def current_unix():
    date_str = f"{str(datetime.datetime.now()).split(" ")[0]} 00:00:00" # Получение текущей даты и форматирование ее
    
    dt = datetime.datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S") # Перевод из даты понятной человеку в компьютерный язык
    unix_time = int(dt.timestamp()) # Перевод в UNIX

    return unix_time


def realised_pnl():
    unix_time = current_unix()

    acc = exchange.privateFuturesGetSettleAccountBook({'settle': SETTLE, 'from': unix_time}) # Получение данных за сегодняшний день
    # Claude советует добавить лимит - 1000, чтобы при активной торговле не утерять часть записей. Пока не считаю это нужным.
    change = 0
    for i in acc:
        type_change = i.get('type')
        if  type_change in ('pnl', 'fund','fee'):
            change += float(i.get("change"))

    return round(change, 2)


def locked_day_behaviour(locked):
    positions = opened_positions()
    price_orders, limit_orders = price_limit_orders()
    cumulative_pnl = 0


    if positions:
        for contract in positions:
            trigger_ts = int(time.time()) # Запись времени, чтобы сверить с закрытием

            try:
                exchange.privateFuturesPostSettleOrders({
                    'settle': SETTLE,
                    'contract': contract,
                    'price': '0',
                    'size': 0,
                    'tif': 'ioc',
                    'close': True
                })

            except Exception:
                log.exception('Не удалось закрыть %s', contract)
                continue

            if not locked: log.warning("Закрыл позицию по %s",contract)




            try:
                time.sleep(0.5)  # Задержка перед получением закрытых позиций
                rows = exchange.privateFuturesGetSettlePositionClose({'settle': SETTLE, 'contract': contract,
                                                                      'limit': 1})  # Получение последней закрытой позиции по контракту

                if rows and int(rows[0]['time']) >= trigger_ts - 2:
                    cumulative_pnl += round(float(rows[0]['pnl']), 2)

            except Exception:
                log.exception('Результат закрытия %s не получен', contract)

            if locked: log.warning("Найдена новая позиция по %s, закрываю", contract)


    if price_orders:
        for contract in price_orders:
            try:
                exchange.privateFuturesDeleteSettlePriceOrders({'settle': SETTLE, 'contract': contract})

                if locked: log.warning("Найден новый условный ордер по %s, закрываю", contract)
                else: log.warning("Закрыл условный ордер по %s", contract)
            except Exception:
                log.exception("Ошибка. Условный ордер %s не закрылся.", contract)


    if limit_orders:
        for contract in limit_orders:
            try:
                exchange.privateFuturesDeleteSettleOrders({'settle': SETTLE, 'contract': contract})

                if locked: log.warning("Найден новый лимитный ордер по %s, закрываю", contract)
                else: log.warning("Закрыл лимитный ордер по %s", contract)
            except Exception:
                log.exception("Ошибка. Лимитный ордер %s не закрылся.", contract)

    return cumulative_pnl


def tg_notif_block(daily_pnl, cumulative_pnl):
    unlock_date = datetime.date.today() + datetime.timedelta(days=1)

    msg = (
        "🚫 <b>Бот заблокирован</b>\n"
        "\n"
        f"Причина: превышен допустимый дневной лимит убытка: {daily_pnl}$\n"
        f"PNL с последней закрытой позиции: {cumulative_pnl}$\n"
        f"🕛 Доступ откроется <b>{unlock_date:%d.%m} в 00:00</b>"
    )

    res = send_message(msg)
    if res and res.get("ok"):
        log.info("Отправил уведомление в телеграмм.")
    else:
        log.warning("Уведомление не отправлено.")


def main():
    exchange.set_sandbox_mode(True) # При запуске бота на демо-счет

    last_refresh = 0
    realised = 0.0
    locked_day = None

    while True:
        try:
            # opened_positions()
            today = datetime.date.today()
            if locked_day == today:
                locked_day_behaviour(locked=True)
                time.sleep(1) # Пауза, чтобы не спамить в Gate запросами каждые 0.5 секунд
            else:

                unrl_pnl = round(float(exchange.privateFuturesGetSettleAccounts({'settle': SETTLE})['unrealised_pnl']),2) # Запрос нереализованного PNL
                now = time.time()
                if now - last_refresh >= 60:
                    realised = realised_pnl()  # Запрос реализованного PNL
                    last_refresh = now

                daily_pnl = round(realised, 2)

                print("Это daily", daily_pnl)

                # multiplier = contract_multiplier() # Множитель для контракта

                if -daily_pnl > MAX_LOSS_USDT:
                   locked_day = today

                   cumulative_pnl = 0
                   try:
                       cumulative_pnl = round(locked_day_behaviour(locked=False),2)
                   except Exception:
                       log.exception('Ошибка при закрытии, доделает режим блокировки')


                       log.warning('Итог закрытия не получен, использую daily=%s', daily_pnl)
                   log.warning(f'Дневной лимит превышен: итог={daily_pnl}. Аккаунт заблокирован.')

                   tg_notif_block(daily_pnl=daily_pnl+cumulative_pnl, cumulative_pnl=cumulative_pnl) # Уведомление в телеграмм
                   print(cumulative_pnl)

            time.sleep(0.5)
        except Exception as e:
            log.exception('Ошибка в цикле')
main()