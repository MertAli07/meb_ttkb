# MEB TTKB Mevzuat - KYS Link Scraper

This script scrapes all links from the "Mevzuat - KYS" dropdown menu on the MEB TTKB website (https://ttkb.meb.gov.tr/). It hovers over "Mevzuat - KYS" to open dropdowns and extracts links from nested menus.

## Installation

1. Make sure you have Python 3.10+ installed
2. Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

Run the scraper:
```bash
python main.py
```

The script will:
1. Open the MEB TTKB website in a browser
2. Find the "Mevzuat - KYS" navbar item
3. Hover over it to open dropdown menus
4. Extract all links from dropdown menus, including nested submenus (like "TTKB Mevzuatı")
5. Save the results to `mevzuat_kys_links.json`
6. Display the links in the console

## Output

The script generates a JSON file (`mevzuat_kys_links.json`) containing an array of link objects:
```json
[
  {
    "text": "Link Text",
    "url": "https://ttkb.meb.gov.tr/..."
  }
]
```

## Requirements

- Python 3.10+
- Chrome browser (for Selenium WebDriver)
- Internet connection

## Notes

- The script uses Selenium with Chrome WebDriver
- ChromeDriver is automatically downloaded via webdriver-manager
- The browser runs in visible mode to allow hover interactions
- Uses Selenium ActionChains to hover over "Mevzuat - KYS" and open dropdowns
- Extracts links from all dropdown levels, including nested submenus (like "TTKB Mevzuatı")
- Handles dynamic dropdown menus that appear on hover

