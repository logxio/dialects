"""Print the parse result at several truncation points, for cross-language diffing."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "langchain" / "src"))

from dialects_page_stats.core import parse_html  # noqa: E402

CUTS = (100, 150, 200, 300, 400, 552)

raw = (ROOT / "fixtures" / "pages" / "article.html").read_bytes()
for cut in CUTS:
    page = parse_html(raw[:cut].decode("utf-8", errors="replace"))
    print(f"{cut}\t{page.title}\t{page.word_count}")
