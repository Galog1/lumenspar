"""AI reading: panel text via Google's Gemini vision model, pixels for facts.

When `Settings.reader_mode` is "ai", every panel's text is read by Gemini
instead of Tesseract, batched several panels per request. Pixel-derived facts
-- artifact rarity, locked/elixir state, weapon refinement badge, character
constellation -- still come from the existing pure-numpy readers. The model's
text goes through the same `build_*` validation as OCR output, so a misread is
refused rather than exported.
"""
