# Project Structure - Price Bot

```
price-bot/
│
├── bot.py                          # Main bot entry point
├── notifier.py                     # Notifications module
├── config.json                     # Project configuration
├── last_prices.json                # Storage of last prices
├── requirements.txt                # Project dependencies
│
├── test.py                         # Main tests
├── telegramtest.py                 # Telegram tests
│
└── shops/                          # Scrapers module by store
    ├── amazon.py                   # Amazon scraper
    ├── fnac.py                     # FNAC scraper
    ├── game.py                     # GAME scraper
    ├── mediamarkt.py               # MediaMarkt scraper
    ├── pccomponentes.py            # PCComponentes scraper
    ├── wakkap.py                   # Wakkap scraper
    ├── xtralife.py                 # Xtralife scraper
    ├── playwright_utils.py         # Playwright utilities
    └── price_utils.py              # Price utilities
```

## Component Description

### Project Root

- **bot.py**: Main entry point for the price tracking bot
- **notifier.py**: Manages notifications (likely Telegram-based)
- **config.json**: Centralized configuration file
- **last_prices.json**: Simple database for storing price history
- **requirements.txt**: Python project dependencies

### Tests

- **test.py**: General project tests
- **telegramtest.py**: Telegram integration-specific tests

### shops/ Module

Contains all store-specific scrapers:

- **Individual scrapers**: amazon.py, fnac.py, game.py, mediamarkt.py, pccomponentes.py, wakkap.py, xtralife.py
- **Utility modules**: 
  - **playwright_utils.py** - Common functions for Playwright automation
    - Browser and page initialization
    - Element waiting and interaction utilities
    - Screenshot and page content extraction
    - Cookie and session management
    - Error handling for web scraping scenarios
  - **price_utils.py** - Common functions for price processing
    - Price parsing and normalization from different formats
    - Currency conversion and standardization
    - Price comparison and tracking logic
    - Historical price analysis and trends
    - Data validation and sanitization
