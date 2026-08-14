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

AMD Ryzen 7 4800H (16 logical cores), 16 GB RAM with ~5.6 GB free, headless Chromium, 2 products × 8 shops = **16 product pages** per run. One run per configuration.

| Workers | Time | Speed-up | Prices retrieved | CPU (avg. cores busy) | Peak RAM | Chromium processes |
| :--- | ---: | ---: | :---: | ---: | ---: | ---: |
| 1 — sequential | 150.7 s | 1.00× | 16 / 16 ✅ | 1.27 of 16 | 1.0 GB | 19 |
| 2 | 81.4 s | 1.85× | 16 / 16 ✅ | 2.31 of 16 | 1.6 GB | 31 |
| 3 | 61.3 s | 2.46× | 16 / 16 ✅ | 3.42 of 16 | 2.1 GB | 41 |
| **4 — default** | **50.7 s** | **2.97×** | **16 / 16 ✅** | **3.99 of 16** | **2.4 GB** | **49** |
| 5 | 45.7 s | 3.30× | 16 / 16 ✅ | 4.88 of 16 | 3.0 GB | 61 |

*Peak RAM is the proportional set size (PSS) of the whole process tree, so pages shared between Chromium helper processes are not counted twice.*

#### Reading the numbers

**Accuracy is unaffected.** All five runs returned the same 16 prices, and every value matched the sequential baseline exactly. Adding workers does not cost correctness, and no shop rate-limited or blocked us — the one-thread-per-shop rule means each site sees exactly the same request pattern it saw sequentially, just alongside other sites.

**Returns diminish, but not evenly.** Since RAM is the limiting resource, the useful measure of an extra worker is how much time it buys per gigabyte it costs:

| Step | Time saved | Extra RAM | Efficiency |
| :--- | ---: | ---: | ---: |
| 1 → 2 | −69.3 s | +0.55 GB | 126 s/GB |
| 2 → 3 | −20.1 s | +0.50 GB | 40 s/GB |
| 3 → 4 | −10.6 s | +0.30 GB | 35 s/GB |
| 4 → 5 | −5.0 s | +0.60 GB | 8 s/GB |

The 3 → 4 step is almost as good a deal as 2 → 3, and it is the cheapest step in the table in absolute memory. The cliff is at **4 → 5**, which costs twice the RAM of the previous step to save half the time. That is where the default sits.

Raw per-worker efficiency still falls — 92% at 2 workers down to 66% at 5 — because the slowest shop sets a floor no amount of parallelism can cross, and the shops are not equally slow.

**CPU is never the bottleneck.** Total CPU time stays roughly flat (192 s sequential vs 223 s at 5 workers) — the same work is simply compressed into less wall time. Even at 5 workers, only ~4.9 of 16 cores were busy on average; the scrapers spend their time waiting on fixed render delays and network, not computing.

**RAM is the real cost.** Roughly **0.5 GB per worker**. Free memory on the test machine went from 4.9 GB down to 3.5 GB at 5 workers. This is the number to watch if you raise the setting — though the gap between 3 and 4 workers is only 0.2 GB of actually-available memory.

#### Recommendation

**4 workers** is the default: it captures a 2.97× speed-up for 2.4 GB, and it is the last step where an extra worker still pays for its memory. A fifth worker saves 5 more seconds for 0.6 GB, which is not a trade worth making.

Drop to 2–3 if you have less than 4 GB of free RAM while the bot runs, or if you run it alongside memory-hungry applications. There is no need to lower it when tracking few shops — the worker count is capped automatically by the number of distinct shops in the check.

---

Carrefour shop is included in the list of available shops for searching the best price of a product, but **only** if you provide the URL manually. It will not appear in the shop selector because the website detects the bot.

Fnac is not available in the shop selector because its website always detects the application as a bot.
