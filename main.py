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
    'apiKey': API_KEY,
    'secret': SECRET_KEY,
    'enableRateLimit': True,
    'options': {'defaultType': 'swap', 'fetchMarkets': {'types': ['swap']}}
    # fetchMarkets lets you choose the market type so the request isn't overloaded.
})


def contract_multiplier(contract):
    multiplier = exchange.publicFuturesGetSettleContractsContract({'settle': SETTLE,
                                                                   'contract': 'BTC_USDT'})
    return multiplier['quanto_multiplier']


def opened_positions():
    positions = exchange.privateFuturesGetSettlePositions(
        {'settle': SETTLE, 'holding': True})  # Information about current positions
    opened_positions = [x['contract'] for x in positions if float(x['size']) != 0]  # Open positions by ticker
    return opened_positions


def price_limit_orders():
    price_ord = exchange.privateFuturesGetSettlePriceOrders({'settle': SETTLE,
                                                             'status': 'open'})  # Conditional orders, such as TP/SL
    price_orders = set([x['initial']['contract'] for x in price_ord])

    limit_ord = exchange.privateFuturesGetSettleOrders({'settle': SETTLE,
                                                        'status': 'open'})  # Limit orders
    limit_orders = set([x['contract'] for x in limit_ord])
    return price_orders, limit_orders


def current_unix():
    date_str = f"{str(datetime.datetime.now()).split(" ")[0]} 00:00:00"  # Get the current date and format it

    dt = datetime.datetime.strptime(date_str,
                                    "%Y-%m-%d %H:%M:%S")  # Convert from a human-readable date to computer language
    unix_time = int(dt.timestamp())  # Convert to UNIX

    return unix_time


def realised_pnl():
    unix_time = current_unix()

    acc = exchange.privateFuturesGetSettleAccountBook({'settle': SETTLE, 'from': unix_time})  # Get data for today
    # Claude advises adding a limit of 1000 so that no records are lost during active trading. I don't consider it necessary for now.
    change = 0
    for i in acc:
        type_change = i.get('type')
        if type_change in ('pnl', 'fund', 'fee'):
            change += float(i.get("change"))

    return round(change, 2)


def locked_day_behaviour(locked):
    positions = opened_positions()
    price_orders, limit_orders = price_limit_orders()
    cumulative_pnl = 0

    if positions:
        for contract in positions:
            trigger_ts = int(time.time())  # Record the time to compare against the closing

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
                log.exception('Failed to close %s', contract)
                continue

            if not locked: log.warning("Closed position for %s", contract)

            try:
                time.sleep(0.5)  # Delay before fetching closed positions
                rows = exchange.privateFuturesGetSettlePositionClose({'settle': SETTLE, 'contract': contract,
                                                                      'limit': 1})  # Get the last closed position for the contract

                if rows and int(rows[0]['time']) >= trigger_ts - 2:
                    cumulative_pnl += round(float(rows[0]['pnl']), 2)

            except Exception:
                log.exception('Closing result for %s not received', contract)

            if locked: log.warning("Found a new position for %s, closing it", contract)

    if price_orders:
        for contract in price_orders:
            try:
                exchange.privateFuturesDeleteSettlePriceOrders({'settle': SETTLE, 'contract': contract})

                if locked:
                    log.warning("Found a new conditional order for %s, closing it", contract)
                else:
                    log.warning("Closed conditional order for %s", contract)
            except Exception:
                log.exception("Error. Conditional order %s was not closed.", contract)

    if limit_orders:
        for contract in limit_orders:
            try:
                exchange.privateFuturesDeleteSettleOrders({'settle': SETTLE, 'contract': contract})

                if locked:
                    log.warning("Found a new limit order for %s, closing it", contract)
                else:
                    log.warning("Closed limit order for %s", contract)
            except Exception:
                log.exception("Error. Limit order %s was not closed.", contract)

    return cumulative_pnl


def tg_notif_block(daily_pnl, cumulative_pnl):
    unlock_date = datetime.date.today() + datetime.timedelta(days=1)

    msg = (
        "🚫 <b>Bot blocked</b>\n"
        "\n"
        f"Reason: the allowed daily loss limit has been exceeded: {daily_pnl}$\n"
        f"PNL from the last closed position: {cumulative_pnl}$\n"
        f"🕛 Access will be restored on <b>{unlock_date:%d.%m} at 00:00</b>"
    )

    res = send_message(msg)
    if res and res.get("ok"):
        log.info("Notification sent to Telegram.")
    else:
        log.warning("Notification was not sent.")


def main():
    exchange.set_sandbox_mode(True)  # When running the bot on a demo account

    last_refresh = 0
    realised = 0.0
    locked_day = None

    while True:
        try:
            # opened_positions()
            today = datetime.date.today()
            if locked_day == today:
                locked_day_behaviour(locked=True)
                time.sleep(1)  # Pause to avoid spamming Gate with requests every 0.5 seconds
            else:

                unrl_pnl = round(float(exchange.privateFuturesGetSettleAccounts({'settle': SETTLE})['unrealised_pnl']),
                                 2)  # Request unrealised PNL
                now = time.time()
                if now - last_refresh >= 60:
                    realised = realised_pnl()  # Request realised PNL
                    last_refresh = now

                daily_pnl = round(realised, 2)

                print("This is daily", daily_pnl)

                # multiplier = contract_multiplier() # Multiplier for the contract

                if -daily_pnl > MAX_LOSS_USDT:
                    locked_day = today

                    cumulative_pnl = 0
                    try:
                        cumulative_pnl = round(locked_day_behaviour(locked=False), 2)
                    except Exception:
                        log.exception('Error while closing, the lock mode will finish it')

                        log.warning('Closing result not received, using daily=%s', daily_pnl)
                    log.warning(f'Daily limit exceeded: total={daily_pnl}. Account blocked.')

                    tg_notif_block(daily_pnl=daily_pnl + cumulative_pnl,
                                   cumulative_pnl=cumulative_pnl)  # Telegram notification
                    print(cumulative_pnl)

            time.sleep(0.5)
        except Exception as e:
            log.exception('Error in the loop')


main()
