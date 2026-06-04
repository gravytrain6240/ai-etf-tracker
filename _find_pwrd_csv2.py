import requests, json, re
from bs4 import BeautifulSoup

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36'}
resp = requests.get('https://www.tcw.com/Products/ETFs/PWRD', headers=headers, timeout=20)
soup = BeautifulSoup(resp.text, 'html.parser')

# Search full page text for CSV/blob URLs
full_text = resp.text

# All vercel blob references
vercel = re.findall(r'mz8ltx6wqoefgvkh\.public\.blob\.vercel-storage\.com/[^\s"\'\\<>]+', full_text)
print("=== Vercel blob URLs in full page ===")
for u in sorted(set(vercel)):
    print(f"  {u}")

# All .csv references
csvs = re.findall(r'[^\s"\'\\<>]+\.csv[^\s"\'\\<>]*', full_text)
print("\n=== CSV references ===")
for u in sorted(set(csvs))[:20]:
    print(f"  {u}")

# API routes
api = re.findall(r'["\'](/api/[^\s"\'\\<>]+)["\']', full_text)
print("\n=== /api/ routes ===")
for u in sorted(set(api))[:20]:
    print(f"  {u}")

# Next.js data fetch calls
next_fetch = re.findall(r'["\'](/_next/data/[^\s"\'\\<>]+)["\']', full_text)
print("\n=== /_next/data/ routes ===")
for u in sorted(set(next_fetch))[:10]:
    print(f"  {u}")

# Print all script src tags
print("\n=== Script sources ===")
for s in soup.find_all('script', src=True):
    print(f"  {s['src'][:100]}")
