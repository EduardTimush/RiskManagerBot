# RiskManagerBot

> Real-time risk management bot for algorithmic crypto trading. Monitors positions and exposure on your exchange account and acts automatically when risk limits are breached.

## Overview

Automated trading needs a safety layer. A strategy can be profitable on paper and still blow up the account because of an oversized position, too much leverage, or a drawdown nobody noticed at 3 a.m.

RiskManagerBot runs as a standalone service next to your trading system. It watches the account in real time and enforces the limits you define, so risk control does not depend on someone watching the screen.

It is built as a self-initiated project to show how I design reliable risk control for trading systems.

## What it monitors


- Position size per symbol
- Total exposure and leverage
- Drawdown daily / total 
- Margin level
- Daily loss limit

## What it does on a breach


- Sends an alert via Telegram 
- Cancels new orders
- Closes positions
- Logs every event with a timestamp for later review

## How it works

```
Exchange API (REST)
        │
        ▼
 Account & position tracker
        │
        ▼
  Rules engine (limits)
        │
        ├──► Alerts (Telegram)
        └──► Actions (cancel orders)
```

## Configuration

Limits are defined in a config file. Example (adjust keys and values to your project):

```yaml
exchange: [gate]
symbols: [BTCUSDT, ETHUSDT]

limits:
  max_position_usd: [value]
  max_leverage: [value]
  max_daily_drawdown_pct: [value]

on_breach:
  alert: true
  action: cancel_orders
```

## Quick start

```bash
git clone https://github.com/EduardTimush/RiskManagerBot.git
cd RiskManagerBot
pip install -r requirements.txt

cp config.example.yaml config.yaml
cp .env.example .env    

python main.py
```

**Test on the exchange testnet first** before connecting a real account.

## Security notes

- Create API keys with the minimum permissions needed. **Disable withdrawals.**
- Store keys in environment variables or a `.env` file, and keep it out of version control.
- [IP whitelisting is recommended where the exchange supports it.]

## Tech stack

Python [ccxt, WebSocket]

## Limitations

- Protection depends on exchange API availability and latency.
- Known limits: e.g. reaction time, supported exchanges and order types.
- This is a safety layer, not a guarantee against losses.

## Disclaimer

This software is an engineering tool. It is not investment advice, and it makes no promises about profit or loss prevention. Use at your own risk.

## Author

Built by Eduard Timush. Open to freelance work on risk management, backtesting and trading automation: [https://www.upwork.com/freelancers/~015fcbfd695964fa34?mp_source=share] or [timuseduard7@gmail.com]

