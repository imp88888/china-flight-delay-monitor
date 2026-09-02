# Pull Request created by GitHub Copilot Chat Assistant

Feature: Add non-official scrape adapters for China flights (Variflight -> Ctrip -> Fliggy)

This PR adds:
- adapters/ (scrape_variflight, scrape_ctrip, scrape_fliggy)
- utils/http.py (request helper with retry, UA rotation, TTL cache)
- tests/fixtures/ and tests/test_variflight.py
- requirements.txt and README.md

Risk notice: This uses non-official scraping. It may violate target sites' terms, be blocked, or break if pages change. Use with caution. Consider official APIs for production or add proxy/pool/IP rotation for production use.
