# Videogame Best Price Bot

---

## Bot that notifies when a videogame price is below a target price that you set in a selected group of shops

---

### Project Structure

You can check the detailed [Project Structure & Component Description](docs/project_structure.md) to understand how the modules and scrapers are organized.

---

More information will be added after the project is finished.

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
