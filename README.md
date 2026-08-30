# Videogame Best Price Bot

---

## Bot that notifies when a videogame price is below a target price that you set in a selected group of shops

---

### Project Structure

You can check the detailed [Project Structure & Component Description](docs/project_structure.md) to understand how the modules and scrapers are organized.

---

## Getting Started

### Requirements

Python 3.11 or newer. Nothing else needs to be installed system-wide.

### 1. Set up the environment — once

```bash
git clone <this-repo> && cd price-bot
python -m venv venv
```

Activate it, then install:

```bash
source venv/bin/activate          # Linux / macOS
venv\Scripts\activate.bat         # Windows

pip install -r requirements.txt
playwright install chromium
```

The last line is **not optional**. Playwright ships no browser of its own, and every price
scraper needs Chromium.

### 2. Choose how you get notified — once

**gear icon → Notifications.** Tick as many as you like; they work at the same time, and each
one has its own *Test* button that sends with what is **typed**, not what is saved, so you can
confirm a password before accepting it. A ticked method has to be filled in before you can save.

| | Reaches you | Needs setting up |
| --- | --- | --- |
| **Desktop notification** | only at this machine | nothing at all |
| **Telegram** | anywhere, on your phone | a bot of your own |
| **Email** | anywhere, and it waits in your inbox | your address + an app password |

How much of one price drop each one sends differs on purpose: Telegram sends **one message per
shop** below your target, email gathers them into **one message** listing all of them cheapest
first, and the desktop shows **only the cheapest** — five popups in a row is not useful. The
*Notify only best price* switch on the Bot tab narrows all three to the cheapest.

#### Telegram

1. Message **@BotFather**, send `/newbot`, follow the prompts — it replies with a **token**
2. Message **@userinfobot**, which replies with your **chat ID**
3. Paste both, and press **Send a test message**

Open a chat with your own bot and press *Start* before testing — Telegram blocks bots from
messaging anyone who has not spoken to them first.

#### Email

Two fields: **your address**, and an **app password**. The SMTP server is worked out from your
address (Gmail, Outlook, Hotmail, Live, Yahoo, iCloud, GMX, AOL, Zoho) and the port defaults to
587, so both of those stay empty unless your provider is an unusual one — a company or
university account, say.

The alert is sent from your own account **to your own account**; there is no separate recipient
field.

**Generating the app password on Gmail.** Your normal account password does not work here —
Google rejects it, and so do Outlook and Yahoo. You need an *app password*: a separate one that
only sends mail, and that you can revoke on its own without changing anything else.

1. Turn on **2-Step Verification** for your Google account — without it the next page does not
   exist
2. Go to **[myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)**
3. Name it `Price Bot` and press **Create**
4. Google shows **16 characters once**, in four groups of four: `abcd efgh ijkl mnop`
5. Type them into the app **without the spaces** → `abcdefghijklmnop`

Then press **Send a test email**. If it fails, it is almost always one of those two things: the
account password instead of an app password, or the spaces left in.

> Other providers are the same idea under a different name — Outlook and Yahoo both call it an
> app password, and it lives in the same security section of the account.

#### Where the credentials are kept

In the app's own database (`tracker.db`), which is gitignored — never in `config.json`, which is
committed. They are **not** encrypted, so treat the machine account as the boundary; an app
password is revocable and can only send mail, which is exactly why it is the right thing to
paste here rather than your real one.

A `.env` in the project root works as a fallback if you prefer keeping them out of the database:

```ini
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
SMTP_USER=you@gmail.com
SMTP_PASSWORD=abcdefghijklmnop
SMTP_HOST=          # only for a provider that is not in the list above
SMTP_PORT=          # only if your network blocks 587
```

The Notifications tab detects this and says *already configured outside the app* instead of
asking again. One caveat for a **packaged build**: there, `.env` has to sit next to the
executable *and* be the working directory, so the Settings dialog is the more reliable route
for anyone running a distributed copy.

### 3. Install the desktop launcher — optional, recommended

Adds **Price Bot** to your application menu so it opens with a double click.

```bash
./launcher/install_launcher.sh                                          # Linux
```
```powershell
powershell -ExecutionPolicy Bypass -File launcher\install_launcher.ps1 -Desktop   # Windows
```

Left click opens the app. Right click offers *Start bot (headless)* and *Stop bot*.
Pass `--uninstall` (Linux) or `-Uninstall` (Windows) to remove it again.

### 4. Run it

Either from the menu entry above, or directly:

| | Linux / macOS | Windows |
| --- | --- | --- |
| Desktop app | `./launcher/start_gui.sh` | `launcher\start_gui.bat` |
| Headless bot | `./launcher/start_bot.sh` | `launcher\start_bot.bat` |
| Stop the bot | `./launcher/stop_bot.sh` | `launcher\stop_bot.bat` |

### 5. First use

From the app window:

1. **Settings Bot** — how often to check, and how notifications behave
2. **Add Product** — the games you want to track, with a target price
3. **Update URLs** — resolves each shop's product page automatically
4. **Start Bot** — runs a price check right away

Run the headless bot only *after* configuring products in the app: it has no settings
interface of its own.

### Sharing it with someone else

```bash
./packaging/build_exe.sh      # build, and download Chromium into the distribution
./packaging/make_release.sh   # zip it, end-user guide included
```

The result is self-contained — Python, Chromium and every dependency are inside. The person
you send it to unzips it, opens the executable, and pastes a Telegram token into Settings.
Nothing to install.

A Windows `.exe` has to be **built on Windows**; PyInstaller does not cross-compile. The
`Build distribution` workflow under the Actions tab does both platforms on GitHub's runners.

> Full details for every script — including what each folder is for — are in the
> [Launch documentation](docs/Lauch_Price_Bot_Documentation.md).

---

### Parallel Scraping

A price check can visit several shops at the same time. Turn it on in **Settings Bot → Parallel scraping** and choose how many shops to scrape at once (2–8, default 4).

Work is split **by shop**, not by product: every URL belonging to a given shop is handled start to finish by one worker, so a site never receives two simultaneous requests. Two consequences follow from that:

* Effective parallelism is capped by the number of **distinct shops** in the check — asking for 5 workers when only 3 shops are configured still uses 3.
* Each worker launches its **own browser**, so memory use grows with the worker count. With Debug mode ON you will also see that many browser windows open at once.

#### Benchmark

AMD Ryzen 7 4800H (16 logical cores), 16 GB RAM with ~5.6 GB free, headless Chromium, 2 products × 8 shops = **16 product pages** per run.

"Page time" is the total time spent inside scrapers, summed across workers. If a page cost the same regardless of how busy the machine is, this column would stay flat and only the wall clock would fall.

| Workers | Wall time | Speed-up | Page time | vs. sequential | Prices retrieved | Peak RAM |
| :--- | ---: | ---: | ---: | ---: | :---: | ---: |
| 1 — sequential | 89.8 s | 1.00× | 89.7 s | — | 16 / 16 ✅ | 1.0 GB |
| 2 | 50.8 s | 1.77× | 99.7 s | +11% | 16 / 16 ✅ | 1.6 GB |
| 3 | 45.8 s | 1.96× | 119.6 s | +33% | 16 / 16 ✅ | 2.0 GB |
| **4 — default** | **34.0 s** | **2.65×** | **124.6 s** | **+39%** | **16 / 16 ✅** | **2.0 GB** |
| 5 | 31.6 s | 2.85× | 143.6 s | +60% | 16 / 16 ✅ | 2.8 GB |

*Peak RAM is the proportional set size (PSS) of the whole process tree, so pages shared between Chromium helper processes are not counted twice. Timings come from one back-to-back run of all five configurations; memory from a separate run of the same workload.*

> **On precision:** these are live shops, and their latency drifts by tens of percent between runs minutes apart. Repeated runs of the same configuration have landed anywhere from 30 s to 54 s at 4 workers. Trust the shape of the table, not its decimals.

#### Reading the numbers

**Accuracy is unaffected.** Every configuration returned all 16 prices, matching the sequential baseline exactly. No shop rate-limited or blocked us — the one-worker-per-shop rule means each site sees the same request pattern it saw sequentially, just alongside other sites.

**Pages get slower as workers are added.** This is the main finding, and it explains the sub-linear speed-up entirely: at 5 workers the same 16 pages cost **60% more** total page time than they do alone. The scrapers are waiting on JavaScript rendering, and renderers from several browsers compete for CPU and memory bandwidth.

It is not scheduling overhead. Instrumenting a 4-worker pass end to end accounts for it precisely: browser launch 0.7 s per worker, shutdown 0.2 s, **1.0 s of overhead in total** on the critical path — the pass runs within 3% of the best possible given what the pages actually cost, and the four workers finish within 2 s of each other.

**Returns diminish sharply after 4.** The 4 → 5 step buys 2.4 s of wall time while inflating page time by another 19 points and adding ~0.8 GB. Below that, each step still pays for itself.

**CPU is not the limit, and neither is bandwidth.** Even at 5 workers only ~4.9 of 16 cores are busy on average. Blocking images, fonts and media was measured twice — sequentially (79.9 s → 84.3 s) and under 4-worker contention (30.6 s → 37.4 s) — and made things **worse** both times: intercepting every request costs more than the bytes it saves.

**RAM is the practical ceiling.** Roughly 0.5 GB per worker. Watch this if you raise the setting on a machine with less than 4 GB free.

#### Recommendation

**4 workers** is the default: it captures a 2.65× speed-up, and it is the last step where an extra worker clearly pays for what it costs in both memory and page-time inflation.

Drop to 2–3 if you have less than 4 GB of free RAM while the bot runs, or if you run it alongside memory-hungry applications. There is no need to lower it when tracking few shops — the worker count is capped automatically by the number of distinct shops in the check.

---

### Scraper Waits

Each scraper waits for the **price element itself** to render (`wait_for_selector`) rather than sleeping a fixed number of seconds. This is both faster and more reliable than the blind sleep it replaced: it continues as soon as the price is on the page, and its budget is set at or above the old sleep, so a genuinely slow page still gets more time than before. Removing those sleeps cut a sequential 8-shop pass from 79.9 s to 50.4 s.

Two rules when changing a price selector, both learned the hard way:

* **Wait for content, not just the element.** Several shops mount an empty price node and fill it in later; waiting for the bare node lets the scraper read nothing and return "no price". Every selector requires the text too — `:has-text('€')`, or `:text-matches("[0-9]")` where the node holds bare digits.
* **`:text-matches` only matches the smallest element containing the text.** If the price is split across a child span, it will never match the outer node — and since the waits are wrapped in `try/except`, that failure is silent and simply burns the whole timeout. Use `:has-text`, which searches descendants.

`project_tests/test_wait_selectors.py` pins both rules against markup copied from the live pages.

---

Carrefour shop is included in the list of available shops for searching the best price of a product, but **only** if you provide the URL manually. It will not appear in the shop selector because the website detects the bot.

Fnac is not available in the shop selector because its website always detects the application as a bot.
