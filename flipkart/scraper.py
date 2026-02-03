import requests
from bs4 import BeautifulSoup
import pandas as pd
import csv
import os
import time
from datetime import datetime
import re
from urllib.parse import urljoin

# --- Configuration ---
SEARCH_URL = "https://www.flipkart.com/clo/cfv/cib/rkt/~cs-xklc0q4u9r/pr?sid=clo,cfv,cib,rkt&collection-tab-name=IndieRemix&pageCriteria=default&p%5B%5D=facets.trend_markers%3D1&param=456789"
CSV_FILE = "flipkart_products.csv"
IMAGE_DIR = "images"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Referer": "https://www.google.com/"
}

# --- Functions ---

def clean_price(price_str):
    """Removes currency symbols and commas from price strings."""
    if not price_str:
        return ""
    # Remove everything except digits
    return re.sub(r'[^\d]', '', price_str)

def sanitize_filename(name):
    """Sanitizes product names for use as filenames."""
    return re.sub(r'[\\/*?:"<>|]', "", name)[:50].strip()

def download_image(url, filename, index):
    """Downloads an image and saves it to the images folder."""
    if not url:
        return "N/A"
    
    if not os.path.exists(IMAGE_DIR):
        os.makedirs(IMAGE_DIR)
        
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code == 200:
            ext = url.split('.')[-1].split('?')[0] # Basic extension extraction
            if len(ext) > 4 or not ext: ext = "jpg"
            
            clean_name = sanitize_filename(filename)
            file_path = os.path.join(IMAGE_DIR, f"{index}_{clean_name}.{ext}")
            
            with open(file_path, 'wb') as f:
                f.write(response.content)
            return file_path
    except Exception as e:
        print(f"Error downloading image {url}: {e}")
    return "Failed"

def fetch_page(url):
    """Fetches the HTML content of a page."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        return response.text
    except Exception as e:
        print(f"Error fetching page {url}: {e}")
        return None

def parse_products(html):
    """Parses product data from Flipkart HTML content."""
    soup = BeautifulSoup(html, 'html.parser')
    products = []
    
    # Flipkart uses 'data-id' for product blocks in most layouts
    containers = soup.find_all(True, {'data-id': True})
    
    if not containers:
        # Fallback to general containers
        containers = soup.select('div._1xHGtK, div._2kHMtA, div._c3472')

    if not containers:
        # Final fallback: find all links that look like product links and look for parent
        potential_links = soup.find_all('a', href=lambda x: x and '/p/' in x)
        seen_parents = set()
        for link in potential_links:
            parent = link.find_parent('div')
            if parent and parent not in seen_parents:
                containers.append(parent)
                seen_parents.add(parent)

    print(f"Found {len(containers)} potential product containers.")

    for idx, item in enumerate(containers, 1):
        try:
            data = {
                "S.No": idx,
                "Date": datetime.now().strftime("%Y-%m-%d"),
                "Product Name": "N/A",
                "MRP": "N/A",
                "Current Price": "N/A",
                "Discount percentage": "N/A",
                "Ratings": "N/A",
                "Number of Reviews": "N/A",
                "Product Image URL": "N/A",
                "Product Page URL": "N/A",
                "Local Image Path": "N/A"
            }

            # 1. Product Page URL
            link_node = item.find('a', href=lambda x: x and '/p/' in x)
            if link_node:
                data["Product Page URL"] = urljoin("https://www.flipkart.com", link_node['href'])

            # 2. Image URL
            img_node = item.find('img')
            if img_node:
                data["Product Image URL"] = img_node.get('src')
                if not data["Product Image URL"] or 'data:image' in data["Product Image URL"]:
                    data["Product Image URL"] = img_node.get('data-src') or img_node.get('srcset')

            # 3. All text parsing (Flipkart often packs info in certain patterns)
            all_text = item.get_text("|", strip=True)
            text_parts = all_text.split("|")
            
            # Heuristic-based extraction
            # Price usually starts with ₹
            prices = [p for p in text_parts if '₹' in p]
            if len(prices) >= 1:
                data["Current Price"] = clean_price(prices[0])
            if len(prices) >= 2:
                data["MRP"] = clean_price(prices[1])
            
            # Discount usually has "off" or "%"
            discounts = [p for p in text_parts if 'off' in p.lower() or '%' in p]
            if discounts:
                data["Discount percentage"] = discounts[0]

            # Product name is often one of the longer text parts near the beginning
            # Or specifically look for certain classes if possible
            name_node = item.select_one('a.IRpwTa, div._4rR01T, a.s1Q9rs, div._2Wk9S9')
            if name_node:
                data["Product Name"] = name_node.get_text(strip=True)
            elif len(text_parts) > 1:
                # Fallback: find longest part that isn't price/discount/rating
                non_data_parts = [p for p in text_parts if '₹' not in p and 'off' not in p.lower() and not re.match(r'^\d\.\d$', p) and len(p) > 5]
                # Filter out common UI noise
                ui_noise = ['Add to Compare', 'Hot Deal', 'Ad', 'Plus', 'Assured']
                clean_parts = [p for p in non_data_parts if not any(noise in p for noise in ui_noise)]
                if clean_parts:
                    data["Product Name"] = clean_parts[0]

            # 4. Ratings & Reviews
            # Strategy A: Specific class match (most common)
            rating_node = item.find(True, class_=lambda x: x and ('3LWZlK' in x or 'Wphh3N' in x))
            if rating_node:
                data["Ratings"] = rating_node.get_text(strip=True)
            
            # Strategy B: Search text for pattern like "4.5"
            if data["Ratings"] == "N/A":
                rating_match = re.search(r'([2-5]\.[0-9])', all_text)
                if rating_match:
                    data["Ratings"] = rating_match.group(1)

            # Strategy C: Review count extraction
            # Look for patterns like "(1,234)" or "123 Ratings" or "123 Reviews"
            reviews_patterns = [
                r'\((\d[, \d]*)\)',  # (1,234)
                r'(\d[, \d]*)\s*Ratings', # 123 Ratings
                r'(\d[, \d]*)\s*Reviews'   # 123 Reviews
            ]
            for pattern in reviews_patterns:
                reviews_match = re.search(pattern, all_text, re.IGNORECASE)
                if reviews_match:
                    data["Number of Reviews"] = reviews_match.group(1).replace(',', '').strip()
                    break
            
            # Fallback for Review count: look for specific review class
            if data["Number of Reviews"] == "N/A":
                review_node = item.find(True, class_=lambda x: x and ('_2_R_oP' in x or '_13vcmD' in x))
                if review_node:
                    rev_text = review_node.get_text(strip=True)
                    rev_match = re.search(r'[\d,]+', rev_text)
                    if rev_match:
                        data["Number of Reviews"] = rev_match.group().replace(',', '')

            # Data Integrity Check
            if data["Product Name"] == "N/A" and data["Current Price"] == "N/A":
                continue

            # Download Image
            if data["Product Image URL"] != "N/A" and data["Product Image URL"]:
                data["Local Image Path"] = download_image(data["Product Image URL"], data["Product Name"], idx)
            
            products.append(data)
            print(f"Scraped: {data['Product Name'][:40]}...")
            
            time.sleep(0.5) # Slight delay

        except Exception as e:
            print(f"Error parsing item {idx}: {e}")
            continue
            
    return products

def main():
    print(f"Starting Flipkart Scraper...")
    print(f"Target URL: {SEARCH_URL}")
    
    html = fetch_page(SEARCH_URL)
    if not html:
        print("Failed to retrieve the page. Exiting.")
        return

    product_data = parse_products(html)
    
    if not product_data:
        print("No products found. Please check selectors or URL.")
        return

    # Create DataFrame and Save to CSV
    df = pd.DataFrame(product_data)
    
    # Ensure correct column order as per requirements
    columns = [
        "S.No", "Date", "Product Name", "MRP", "Current Price", 
        "Discount percentage", "Ratings", "Number of Reviews", 
        "Product Image URL", "Product Page URL", "Local Image Path"
    ]
    df = df[columns]
    
    df.to_csv(CSV_FILE, index=False, encoding='utf-8-sig')
    print(f"\nSuccess! Scraped {len(product_data)} products.")
    print(f"Data saved to {CSV_FILE}")
    print(f"Images saved to {IMAGE_DIR}/ folder")

if __name__ == "__main__":
    main()
