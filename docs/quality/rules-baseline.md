# Extraction quality: rules-v1

Measured on the synthetic library-kiosk set in `data/eval` (17 expected claims).

| Source | Expected | Found | Recall | Produced | Correct | Precision |
|---|---|---|---|---|---|---|
| chat | 9 | 0 | 0% | 0 | 0 | 0% |
| notes | 5 | 5 | 100% | 5 | 5 | 100% |
| tasks | 3 | 3 | 100% | 3 | 3 | 100% |
| **all** | 17 | 8 | 47% | 8 | 8 | 100% |

- Decision reasons kept: 1 of 3
- Confidence labels given: verified 8
- Quotes that could not be found in their source: 0
- Claims labelled quote-verified that match nothing expected: 0

Missed: chat-sqlite, chat-scanner, chat-latefee-owner, chat-printer, chat-domain, chat-router, chat-backup, chat-wifi, chat-priya

Note: 14 chat messages were not interpreted: the rule-based extractor only reads structured sources. Use an LLM extractor to read chat.
