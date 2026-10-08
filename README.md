# shopbot

A Telegram shop bot: catalog, cart, coupons, checkout, order tracking and an owner admin panel.
**Pure Python 3.10+, no third-party packages.** It talks to the Telegram Bot API directly, so there is nothing to install and nothing that breaks when a library changes.

> Portfolio / demo project. Payments are **cash on delivery** and **manual bank transfer** (the bot shows your bank details and an order reference). There is no card processing.

## What it does

**For customers** (English, Persian, Turkish; each user picks their language)
- Browse categories and products with photos, price and live stock
- Cart with +/- buttons, coupon codes, stock checks at every step
- Checkout in four steps: name, phone (or "share my number"), address, payment method
- Order history, order status notifications, cancel an order while it is still new
- Product search

**For the shop owner** (`/admin`, only for IDs in `ADMIN_IDS`)
- New-order alerts with an "Open" button
- Move orders through `new → confirmed → shipped → delivered` (or cancel); the customer is notified in their language
- Add products (name, price, stock, description, photo), change price/stock, hide/show
- Create categories and coupon codes (percent and max uses)
- Stats: orders by status, revenue, top sellers, low-stock list
- Broadcast a message to all customers (with a confirmation step)
- Export all orders as CSV (Excel-safe, formula-injection safe)

## First impression (before and after START)

- **Before START:** the bot's profile shows a picture, a description and a short description in English, Persian and Turkish, plus a command menu (`/start`, `/menu`, `/help`, `/cancel`; the owner also sees `/admin`). The bot publishes the texts and commands by itself on every start (`python -m shopbot --setup` does only that).
- **Picture on that pre-START screen:** Telegram does not allow bots to set it through the API. Set it once in @BotFather: `/mybots` → your bot → *Edit Bot* → *Edit Description Picture* → send `shopbot/assets/description_pic.png` (640×360).
- **After START:** the welcome screen is a banner picture with the language picker, then the main menu. The banner is uploaded once and reused through its Telegram file ID. If the picture cannot be sent, the bot falls back to plain text.
- **Your own branding:** edit the three constants at the top of `tools/make_banner.py` (shop name, tagline, category chips) and run it. It rewrites both pictures (needs `playwright`).

## Try it in 30 seconds, no Telegram token needed

```
python -m shopbot --simulate           # play a customer
python -m shopbot --simulate --admin   # play the shop owner
```

Buttons appear as numbered options; type the number to press one.

## Run the real bot

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token.
2. Find your own numeric Telegram ID (for example with @userinfobot).
3. ```
   cp .env.example .env      # fill in BOT_TOKEN and ADMIN_IDS
   python -m shopbot --check # verifies the token
   python -m shopbot --seed  # runs the bot and adds a demo catalog if the database is empty
   ```

With Docker: `docker build -t shopbot . && docker run --env-file .env -v shopdata:/data shopbot`

## Configuration (`.env`)

| Variable | Meaning | Default |
|---|---|---|
| `BOT_TOKEN` | token from BotFather | required |
| `ADMIN_IDS` | comma-separated Telegram IDs allowed to use `/admin` | none |
| `DB_PATH` | SQLite file | `shop.db` |
| `CURRENCY` | shown after every price | `USD` |
| `SHOP_NAME` | shown in the welcome message | `Demo Shop` |
| `BANK_DETAILS` | text shown for bank-transfer orders (`\n` for new lines) | placeholder |

## Design notes

- **Money is integer cents** everywhere; discounts round down in whole cents.
- **Stock cannot be oversold.** Order creation runs in one `BEGIN IMMEDIATE` transaction that re-checks every line, so two customers cannot both buy the last unit. A failed order changes nothing. Cancelling restores stock and the coupon use.
- **Status workflow is enforced** in one place (`orders.TRANSITIONS`), not in the UI.
- **All user text is HTML-escaped** before it is sent (the bot uses `parse_mode=HTML`), and CSV cells starting with `= + - @` are neutralised.
- **A shared contact must be the sender's own.** The bot ignores a forwarded contact card for someone else.
- **One bad update never stops the bot.** Errors are logged and the user gets a generic message; Telegram flood-control (`retry_after`) and network errors are retried with backoff.
- **Layers:** `catalog/cart/orders` (business rules, no Telegram) → `views` (pure functions: data → text + keyboard) → `bot` (routing and conversation state) → `api` (HTTP). The first two layers are tested without any bot at all.
- Conversation state (checkout, admin forms) lives in SQLite, so a restart does not lose a half-finished checkout.

```
shopbot/
  api.py        Telegram HTTP client (urllib, retries, multipart upload)
  bot.py        update routing, checkout flow, admin flow
  views.py      screens: (text, inline keyboard)
  catalog.py    categories, products, search
  cart.py       cart, coupons, totals
  orders.py     order creation, workflow, stats, CSV
  i18n.py       English / Persian / Turkish texts
  db.py         SQLite schema and transactions
  profile.py    pre-START description, short description, command menu (3 languages)
  simulator.py  terminal simulator
  assets/       banner.png (in chat), description_pic.png (for BotFather)
tools/make_banner.py   regenerates both pictures with your shop name
tests/          65 tests: services, bot flows, welcome banner, profile setup, i18n completeness, HTTP client against a local stub server
```

## Tests

```
python -m unittest discover -s tests -t .
```

The HTTP client is tested against a local stub server (success, API errors, flood control, multipart upload, unreachable network). Bot flows are tested end to end with simulated Telegram updates.

## Limits (honest list)

- The bot logic and the HTTP client are tested against a simulated Telegram, not against live Telegram servers. Run `python -m shopbot --check` with your token to confirm connectivity.
- Long polling, single process, single SQLite connection: right for a small shop, not for thousands of simultaneous users. Switching to webhooks and PostgreSQL would be the next step.
- Admin screens are English only. Product names and descriptions are entered once, in one language.
- No online card payments, shipping-cost calculation or tax rules.

## License

MIT
