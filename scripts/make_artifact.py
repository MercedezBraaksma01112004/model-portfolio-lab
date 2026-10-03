"""Convert output/dashboard.html into a body-only fragment for hosting platforms that wrap
the page in their own skeleton (Claude Artifacts). Usage: python scripts/make_artifact.py [in] [out]"""
import re, sys
from pathlib import Path
src = Path(sys.argv[1] if len(sys.argv) > 1 else "output/dashboard.html").read_text(encoding="utf-8")
out = Path(sys.argv[2] if len(sys.argv) > 2 else "output/dashboard_artifact.html")
head = re.search(r"<head>(.*?)</head>", src, re.S).group(1)
body = re.search(r"<body>(.*?)</body>", src, re.S).group(1)
keep = "\n".join(m.group(0) for m in re.finditer(r"<title>.*?</title>|<link[^>]*>|<style>.*?</style>", head, re.S))
out.write_text(keep + "\n" + body, encoding="utf-8")
print(out)
