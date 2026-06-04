import requests, json, re
from bs4 import BeautifulSoup

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36'}
resp = requests.get('https://www.tcw.com/Products/ETFs/PWRD', headers=headers, timeout=20)
soup = BeautifulSoup(resp.text, 'html.parser')

# 1. All links containing csv, download, holding, portfolio
print("=== Links with csv/holding/portfolio/download ===")
for a in soup.find_all('a', href=True):
    href = a['href']
    text = a.get_text(strip=True)
    if any(k in href.lower() or k in text.lower() for k in ['csv', 'holding', 'portfolio', 'download', 'xlsx']):
        print(f'  [{text[:40]}] -> {href[:120]}')

# 2. All select/option elements (dropdowns)
print("\n=== Dropdown elements ===")
for sel in soup.find_all('select'):
    print(f"  select name={sel.get('name','')} id={sel.get('id','')}")
    for opt in sel.find_all('option'):
        print(f"    option value={opt.get('value','')} text={opt.get_text(strip=True)[:50]}")

# 3. All buttons
print("\n=== Buttons with relevant text ===")
for btn in soup.find_all(['button', 'input']):
    text = btn.get_text(strip=True) or btn.get('value', '')
    if any(k in text.lower() for k in ['hold', 'download', 'csv', 'export', 'portfolio']):
        print(f"  {btn.name}: [{text[:50]}]  data-attrs={[f'{k}={btn.get(k)}' for k in btn.attrs if 'data' in k][:5]}")

# 4. Look in __NEXT_DATA__ for csv URLs or holding data
next_data = soup.find('script', id='__NEXT_DATA__')
if next_data:
    text = next_data.string or ''
    # Find any .csv or vercel storage references
    csv_refs = re.findall(r'["\']([^"\']*(?:csv|holdings|portfolio)[^"\']*)["\']', text, re.IGNORECASE)
    print("\n=== CSV/holdings refs in __NEXT_DATA__ ===")
    for ref in sorted(set(csv_refs))[:30]:
        print(f"  {ref[:120]}")
