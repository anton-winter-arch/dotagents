# flowkit

A small codebase that summarizes zone flow readings.

The entry point is `app/main.py`; zones are summarized by the util module (`app/util.py`) and every reading is clamped by the helpers (`app/helpers.py`).

Zone alerts are raised by [app/alerts.py](app/alerts.py) under the rules in [docs/alerts.md](docs/alerts.md); per-zone thresholds live in [data/thresholds.json](data/thresholds.json).

Run the tests with:

```bash
python3 -m unittest discover -s tests -t .
```
