from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import time
import json
import os
from urllib.parse import urljoin

TARGET_TEXT = "Mevzuat - KYS"
S3_BUCKET_NAME = "goaltech-poc-ai-assistant"
S3_OUTPUT_KEY = os.getenv("S3_OUTPUT_KEY", "extract-links/mertali.json")


def scrape_mevzuat_kys_links():
    """
    Scrapes all links from the TARGET_TEXT dropdown menu.
    Returns a list of dictionaries containing link text and URLs.
    """
    # Setup Chrome options - run headless for EC2
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    # Initialize the driver
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    actions = ActionChains(driver)

    links_found = []

    try:
        # Navigate to the website
        base_url = "https://ttkb.meb.gov.tr/"
        print(f"Navigating to {base_url}...")
        driver.get(base_url)

        # Wait for page to load
        time.sleep(3)

        # Find the TARGET_TEXT navbar item
        print(f"Looking for '{TARGET_TEXT}' navbar item...")

        mevzuat_item = None

        # Try multiple selectors to find the TARGET_TEXT item
        selectors = [
            f"//a[contains(text(), '{TARGET_TEXT}')]",
            f"//span[contains(text(), '{TARGET_TEXT}')]",
            f"//li[contains(text(), '{TARGET_TEXT}')]",
        ]

        for selector in selectors:
            try:
                elements = driver.find_elements(By.XPATH, selector)
                for elem in elements:
                    if elem.is_displayed():
                        # Get the parent li or the element itself
                        try:
                            mevzuat_item = elem.find_element(By.XPATH, "./ancestor::li[1]")
                        except Exception:
                            mevzuat_item = elem.find_element(By.XPATH, "./..")
                        print(f"Found '{TARGET_TEXT}' using selector: {selector}")
                        break
                if mevzuat_item:
                    break
            except Exception:
                continue

        if not mevzuat_item:
            # Try finding by partial text
            try:
                link = driver.find_element(By.PARTIAL_LINK_TEXT, "Mevzuat")
                mevzuat_item = link.find_element(By.XPATH, "./ancestor::li[1]")
                print(f"Found '{TARGET_TEXT}' using partial link text")
            except Exception:
                pass

        if not mevzuat_item:
            print(f"Error: Could not find '{TARGET_TEXT}' navbar item!")
            return []

        all_links = set()  # Use set to avoid duplicates - stores (text, url, path) tuples
        base_path = [TARGET_TEXT]  # Base path for all links

        # Process the TARGET_TEXT item
        print(f"\nProcessing '{TARGET_TEXT}' dropdown...")
        try:
            # Scroll to the element
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", mevzuat_item)
            time.sleep(0.5)

            # Hover over TARGET_TEXT to open dropdown
            print(f"Hovering over '{TARGET_TEXT}'...")
            try:
                actions.move_to_element(mevzuat_item).perform()
                time.sleep(1.5)  # Wait for dropdown to appear
                print("  Dropdown opened")
            except Exception as e:
                print(f"  Could not hover: {e}")
                return []

            # Wait a bit for dropdown animations
            time.sleep(1.5)

            # Find dropdown menus that appeared after hovering
            # Filter out common navbar links that shouldn't be included
            excluded_texts = ["Anasayfa", "RSS", "S.S.S", "İletişim", "Home", "Contact", "EN", "TR"]
            excluded_urls = [
                base_url,
                base_url.rstrip("/"),
                "https://ttkb.meb.gov.tr/meb_iys_dosyalar/index.html",
            ]

            dropdown_found = False
            processed_dropdowns = set()

            # Find all visible dropdown menus (simpler approach - get all visible dropdowns)
            dropdown_selectors = [
                "//div[contains(@class, 'sub-dropdown-container')]",
                "//div[contains(@class, 'dropdown-container')]",
                "//div[contains(@class, 'dropdown-menu')]",
                "//ul[contains(@class, 'dropdown-menu')]",
                "//div[contains(@class, 'submenu')]",
                "//ul[contains(@class, 'submenu')]",
            ]

            for selector in dropdown_selectors:
                try:
                    dropdowns = driver.find_elements(By.XPATH, selector)
                    print(f"  Found {len(dropdowns)} dropdowns with selector: {selector}")
                    for dropdown in dropdowns:
                        try:
                            if dropdown.is_displayed() and id(dropdown) not in processed_dropdowns:
                                processed_dropdowns.add(id(dropdown))
                                dropdown_found = True
                                print(
                                    "  Processing dropdown menu "
                                    f"(ID: {dropdown.get_attribute('id') or 'no-id'})"
                                )

                                # Extract all links from this dropdown
                                # Look for links in ul elements, especially those with class "alt-menu"
                                dropdown_links = dropdown.find_elements(
                                    By.XPATH,
                                    ".//ul//li[contains(@class, 'alt-menu')]//a[@href] | .//a[@href]",
                                )
                                print(f"    Found {len(dropdown_links)} links in dropdown")

                                if len(dropdown_links) == 0:
                                    # Try alternative XPath if no links found
                                    dropdown_links = dropdown.find_elements(By.XPATH, ".//a[@href]")
                                    print(
                                        f"    Found {len(dropdown_links)} links with alternative XPath"
                                    )

                                for link in dropdown_links:
                                    try:
                                        href = link.get_attribute("href")
                                        text = link.text.strip()

                                        # Skip excluded links by text
                                        if text in excluded_texts:
                                            print(f"    Skipping excluded text: {text}")
                                            continue

                                        if href and href not in ["#", "", None, "javascript:void(0)"]:
                                            full_url = urljoin(base_url, href)

                                            # Skip excluded URLs (base URL, etc.)
                                            if full_url in excluded_urls:
                                                print(f"    Skipping excluded URL: {full_url}")
                                                continue

                                            # Skip if it's just the base URL
                                            if full_url == base_url or full_url == base_url.rstrip("/"):
                                                print(f"    Skipping base URL: {full_url}")
                                                continue

                                            if text:
                                                path_tuple = tuple(base_path)
                                                all_links.add((text, full_url, path_tuple))
                                                print(
                                                    "    ✓ Added: "
                                                    f"{text}: {full_url} "
                                                    f"(Path: {' --> '.join(path_tuple)})"
                                                )
                                        else:
                                            print(f"    Skipping invalid link: href={href}, text={text}")
                                    except Exception as e:
                                        print(f"    Error processing link: {e}")
                                        continue

                                # First, extract all direct links from the main dropdown
                                print(
                                    f"    Extracted {len(dropdown_links)} direct links from main dropdown"
                                )

                                # Now find nested submenu items (like "TTKB Mevzuatı")
                                # Find all list items that might have submenus - look for items with spans
                                nested_items = []

                                # Find items with spans (likely submenu headers)
                                all_li_items = dropdown.find_elements(By.XPATH, ".//li")
                                for li in all_li_items:
                                    try:
                                        # Check if this li contains a span (submenu header indicator)
                                        span = li.find_element(By.XPATH, ".//span")
                                        span_text = span.text.strip() if span else ""

                                        # Check if this li has a submenu class or contains a span
                                        li_classes = li.get_attribute("class") or ""
                                        if (
                                            "mt-lg-1" in span.get_attribute("class")
                                            or "submenu" in li_classes.lower()
                                            or span_text
                                        ):
                                            if li not in nested_items:
                                                nested_items.append(li)
                                    except Exception:
                                        pass

                                # Also find items with dropdown/submenu classes
                                class_based_items = dropdown.find_elements(
                                    By.XPATH,
                                    ".//li[contains(@class, 'dropdown') or "
                                    "contains(@class, 'submenu') or contains(@class, 'has-submenu')]",
                                )
                                for item in class_based_items:
                                    if item not in nested_items:
                                        nested_items.append(item)

                                # Find spans with mt-lg-1 class and get their parent li
                                mt_spans = dropdown.find_elements(
                                    By.XPATH, ".//span[contains(@class, 'mt-lg-1')]"
                                )
                                for span in mt_spans:
                                    try:
                                        parent_li = span.find_element(By.XPATH, "./ancestor::li[1]")
                                        if parent_li not in nested_items:
                                            nested_items.append(parent_li)
                                    except Exception:
                                        pass

                                print(f"    Found {len(nested_items)} nested items to process")

                                # Process each nested item
                                for idx, nested_item in enumerate(nested_items, 1):
                                    try:
                                        # Try to get text from span first (like "TTKB Mevzuatı")
                                        nested_text = ""
                                        try:
                                            span = nested_item.find_element(By.XPATH, ".//span")
                                            nested_text = span.text.strip()
                                        except Exception:
                                            nested_text = nested_item.text.strip()

                                        if not nested_text or nested_text in excluded_texts:
                                            continue

                                        print(
                                            f"  [{idx}/{len(nested_items)}] "
                                            f"Processing nested item: {nested_text[:60]}..."
                                        )

                                        # Hover over nested item to open submenu
                                        actions.move_to_element(nested_item).perform()
                                        time.sleep(2)  # Wait longer for submenu to appear

                                        # Find all visible submenus that appeared after hovering
                                        # Look for submenus that are siblings or children of the nested item
                                        submenu_links_found = []

                                        # Strategy 1: Find submenus that are siblings or following the nested item
                                        try:
                                            # Look for ul or div elements that are siblings
                                            sibling_submenus = nested_item.find_elements(
                                                By.XPATH,
                                                "./following-sibling::*[contains(@class, 'submenu')] | "
                                                "./following-sibling::*[contains(@class, 'dropdown-menu')]",
                                            )
                                            for submenu in sibling_submenus:
                                                if submenu.is_displayed():
                                                    links = submenu.find_elements(By.XPATH, ".//a[@href]")
                                                    submenu_links_found.extend(links)
                                        except Exception:
                                            pass

                                        # Strategy 2: Find all visible submenus globally and check if related
                                        try:
                                            all_submenus = driver.find_elements(
                                                By.XPATH,
                                                "//div[contains(@class, 'sub-dropdown-container')] | "
                                                "//div[contains(@class, 'dropdown-container')] | "
                                                "//div[contains(@class, 'submenu')] | "
                                                "//ul[contains(@class, 'submenu')] | "
                                                "//div[contains(@class, 'dropdown-menu')] | "
                                                "//ul[contains(@class, 'dropdown-menu')]",
                                            )
                                            for submenu in all_submenus:
                                                try:
                                                    if (
                                                        submenu.is_displayed()
                                                        and id(submenu) not in processed_dropdowns
                                                    ):
                                                        # Extract links from ul elements, especially alt-menu
                                                        links = submenu.find_elements(
                                                            By.XPATH,
                                                            ".//ul//li[contains(@class, 'alt-menu')]"
                                                            "//a[@href] | .//a[@href]",
                                                        )
                                                        submenu_links_found.extend(links)
                                                except Exception:
                                                    continue
                                        except Exception:
                                            pass

                                        # Strategy 3: Find links in the nested item's structure
                                        try:
                                            item_links = nested_item.find_elements(
                                                By.XPATH,
                                                ".//a[@href] | ./following-sibling::*//a[@href] | "
                                                "./following::*[contains(@class, 'submenu')]//a[@href]",
                                            )
                                            submenu_links_found.extend(item_links)
                                        except Exception:
                                            pass

                                        print(
                                            f"    Found {len(submenu_links_found)} "
                                            "potential links from submenu"
                                        )

                                        # Extract and add all found links
                                        for link in submenu_links_found:
                                            try:
                                                if not link.is_displayed():
                                                    continue

                                                href = link.get_attribute("href")
                                                text = link.text.strip()

                                                # Skip excluded links
                                                if text in excluded_texts:
                                                    continue

                                                if href and href not in [
                                                    "#",
                                                    "",
                                                    None,
                                                    "javascript:void(0)",
                                                ]:
                                                    full_url = urljoin(base_url, href)

                                                    # Skip excluded URLs
                                                    if full_url in excluded_urls:
                                                        continue

                                                    # Skip base URL
                                                    if (
                                                        full_url == base_url
                                                        or full_url == base_url.rstrip("/")
                                                    ):
                                                        continue

                                                    if text:
                                                        # Path includes nested item text
                                                        current_path = base_path + [nested_text]
                                                        path_tuple = tuple(current_path)
                                                        all_links.add((text, full_url, path_tuple))
                                                        print(
                                                            "      ✓ Added: "
                                                            f"{text}: {full_url} "
                                                            f"(Path: {' --> '.join(path_tuple)})"
                                                        )
                                            except Exception:
                                                continue

                                        # Move back to parent item to keep dropdown open
                                        actions.move_to_element(mevzuat_item).perform()
                                        time.sleep(0.8)

                                    except Exception as e:
                                        print(f"    Error processing nested item: {e}")
                                        import traceback

                                        traceback.print_exc()
                                        # Move back to parent on error too
                                        try:
                                            actions.move_to_element(mevzuat_item).perform()
                                            time.sleep(0.5)
                                        except Exception:
                                            pass
                                        continue
                        except Exception as e:
                            print(f"  Error processing dropdown: {e}")
                            continue
                except Exception as e:
                    print(f"  Error with selector {selector}: {e}")
                    continue

            # Always try to find links in the dropdown structure
            print("  Extracting all links from visible dropdown structure...")

            # Approach 1: Find sub-dropdown-container elements specifically
            try:
                # Look for sub-dropdown-container elements
                sub_dropdowns = driver.find_elements(
                    By.XPATH,
                    "//div[contains(@class, 'sub-dropdown-container')] | "
                    "//div[contains(@class, 'dropdown-container')]",
                )
                print(f"  Found {len(sub_dropdowns)} sub-dropdown-container elements")

                # Also try to find links directly without checking visibility first
                all_links_in_containers = driver.find_elements(
                    By.XPATH,
                    "//div[contains(@class, 'sub-dropdown-container')]//a[@href] | "
                    "//div[contains(@class, 'dropdown-container')]//a[@href]",
                )
                print(
                    f"  Found {len(all_links_in_containers)} total links in all containers "
                    "(without visibility check)"
                )

                # Process these links directly
                for link in all_links_in_containers:
                    try:
                        href = link.get_attribute("href")
                        text = link.text.strip()

                        # Skip empty text or href
                        if not text or not href:
                            continue

                        # Skip excluded links
                        if text in excluded_texts:
                            continue

                        if href and href not in ["#", "", None, "javascript:void(0)"]:
                            full_url = urljoin(base_url, href)

                            # Skip excluded URLs
                            if full_url in excluded_urls:
                                continue

                            # Skip base URL
                            if full_url == base_url or full_url == base_url.rstrip("/"):
                                continue

                            if text:
                                path_tuple = tuple(base_path)
                                all_links.add((text, full_url, path_tuple))
                                print(
                                    "    ✓ Added from direct container search: "
                                    f"{text}: {full_url} "
                                    f"(Path: {' --> '.join(path_tuple)})"
                                )
                    except Exception:
                        continue

                visible_count = 0
                for idx, sub_dropdown in enumerate(sub_dropdowns, 1):
                    try:
                        is_visible = sub_dropdown.is_displayed()
                        if is_visible:
                            visible_count += 1

                        # Extract links regardless of visibility
                        links = sub_dropdown.find_elements(
                            By.XPATH,
                            ".//ul//li[contains(@class, 'alt-menu')]//a[@href] | .//a[@href]",
                        )

                        if len(links) == 0:
                            # Try alternative XPath if no links found
                            links = sub_dropdown.find_elements(By.XPATH, ".//a[@href]")

                        if len(links) > 0:
                            print(
                                f"    [{idx}/{len(sub_dropdowns)}] "
                                f"Visible: {is_visible}, "
                                f"Found {len(links)} links in sub-dropdown-container"
                            )

                        for link in links:
                            try:
                                # Don't check visibility
                                href = link.get_attribute("href")
                                text = link.text.strip()

                                # Skip empty text or href
                                if not text or not href:
                                    continue

                                # Skip excluded links
                                if text in excluded_texts:
                                    continue

                                if href and href not in ["#", "", None, "javascript:void(0)"]:
                                    full_url = urljoin(base_url, href)

                                    # Skip excluded URLs
                                    if full_url in excluded_urls:
                                        continue

                                    # Skip base URL
                                    if full_url == base_url or full_url == base_url.rstrip("/"):
                                        continue

                                    if text:
                                        path_tuple = tuple(base_path)
                                        all_links.add((text, full_url, path_tuple))
                                        print(
                                            "    ✓ Added from sub-dropdown: "
                                            f"{text}: {full_url} "
                                            f"(Path: {' --> '.join(path_tuple)})"
                                        )
                            except Exception as e:
                                print(f"    Error processing link: {e}")
                                continue
                    except Exception:
                        continue
            except Exception as e:
                print(f"  Error finding sub-dropdown-containers: {e}")

            # Approach 2: Find all visible links after hover that are in dropdown-like structures
            try:
                # Look for any visible ul or div that might be a dropdown
                all_dropdown_candidates = driver.find_elements(
                    By.XPATH, "//ul | //div[contains(@class, 'menu')] | //div[contains(@class, 'nav')]"
                )

                for candidate in all_dropdown_candidates:
                    try:
                        if candidate.is_displayed():
                            # Look for links in ul elements with alt-menu class
                            candidate_links = candidate.find_elements(
                                By.XPATH,
                                ".//ul//li[contains(@class, 'alt-menu')]//a[@href] | .//a[@href]",
                            )

                            for link in candidate_links:
                                try:
                                    if not link.is_displayed():
                                        continue

                                    href = link.get_attribute("href")
                                    text = link.text.strip()

                                    # Skip excluded links
                                    if text in excluded_texts:
                                        continue

                                    if href and href not in ["#", "", None, "javascript:void(0)"]:
                                        full_url = urljoin(base_url, href)

                                        # Skip excluded URLs
                                        if full_url in excluded_urls:
                                            continue

                                        # Skip base URL
                                        if full_url == base_url or full_url == base_url.rstrip("/"):
                                            continue

                                        if text:
                                            path_tuple = tuple(base_path)
                                            all_links.add((text, full_url, path_tuple))
                                            print(
                                                "    ✓ Added from candidate: "
                                                f"{text}: {full_url} "
                                                f"(Path: {' --> '.join(path_tuple)})"
                                            )
                                except Exception:
                                    continue
                    except Exception:
                        continue
            except Exception as e:
                print(f"  Error finding dropdown candidates: {e}")

            # Approach 2: Find all links directly under mevzuat_item and its descendants
            print("  Trying fallback: Finding links under mevzuat_item...")
            try:
                # Get all links that are descendants of mevzuat_item
                all_item_links = mevzuat_item.find_elements(By.XPATH, ".//a[@href]")
                print(f"  Found {len(all_item_links)} links under mevzuat_item")

                for link in all_item_links:
                    try:
                        if not link.is_displayed():
                            continue

                        href = link.get_attribute("href")
                        text = link.text.strip()

                        # Skip excluded links
                        if text in excluded_texts:
                            print(f"    Skipping excluded: {text}")
                            continue

                        if href and href not in ["#", "", None, "javascript:void(0)"]:
                            full_url = urljoin(base_url, href)

                            # Skip excluded URLs
                            if full_url in excluded_urls:
                                print(f"    Skipping excluded URL: {full_url}")
                                continue

                            # Skip base URL
                            if full_url == base_url or full_url == base_url.rstrip("/"):
                                print(f"    Skipping base URL: {full_url}")
                                continue

                            if text:
                                path_tuple = tuple(base_path)
                                all_links.add((text, full_url, path_tuple))
                                print(
                                    "    ✓ Added from item: "
                                    f"{text}: {full_url} "
                                    f"(Path: {' --> '.join(path_tuple)})"
                                )
                        else:
                            print(f"    Skipping invalid link: href={href}, text={text}")
                    except Exception as e:
                        print(f"    Error processing link: {e}")
                        continue

                # Now find nested items (like "TTKB Mevzuatı") and hover over them
                print("  Looking for nested items to hover...")
                try:
                    # Find all li elements under mevzuat_item that might be nested submenu headers
                    all_li_under_item = mevzuat_item.find_elements(By.XPATH, ".//li")
                    print(f"  Found {len(all_li_under_item)} li elements under mevzuat_item")

                    nested_items_to_hover = []
                    for li in all_li_under_item:
                        try:
                            # Check if this li contains a span
                            span = li.find_element(By.XPATH, ".//span")
                            span_text = span.text.strip() if span else ""
                            li_text = li.text.strip()

                            # If it has a span or looks like a header, it might be nested
                            if span_text and span_text not in excluded_texts and li_text:
                                if li not in nested_items_to_hover:
                                    nested_items_to_hover.append(li)
                                    print(f"    Found potential nested item: {span_text[:50]}...")
                        except Exception:
                            # No span, but might still be a nested item
                            li_text = li.text.strip()
                            if li_text and li_text not in excluded_texts:
                                # Check if it's not just a direct link
                                try:
                                    link_in_li = li.find_element(By.XPATH, ".//a[@href]")
                                    href = link_in_li.get_attribute("href")
                                    # If it's just a base URL link, it might be a header
                                    if href == base_url or href == base_url.rstrip("/") or not href:
                                        if li not in nested_items_to_hover:
                                            nested_items_to_hover.append(li)
                                except Exception:
                                    pass
                except Exception as e:
                    print(f"  Error finding nested items: {e}")

                    # Hover over each nested item to open submenus
                    for idx, nested_item in enumerate(nested_items_to_hover, 1):
                        try:
                            # Try to get text from span first (like "TTKB Mevzuatı")
                            nested_text = ""
                            try:
                                span = nested_item.find_element(By.XPATH, ".//span")
                                nested_text = span.text.strip()
                            except Exception:
                                nested_text = nested_item.text.strip()

                            print(
                                f"  [{idx}/{len(nested_items_to_hover)}] "
                                f"Hovering over nested item: {nested_text[:50]}..."
                            )

                            # Hover over nested item
                            actions.move_to_element(nested_item).perform()
                            time.sleep(2)  # Wait for submenu to appear

                            # Find all newly visible links after hovering
                            new_links = driver.find_elements(
                                By.XPATH,
                                "//div[contains(@class, 'sub-dropdown-container')]"
                                "//ul//li[contains(@class, 'alt-menu')]//a[@href] | "
                                "//div[contains(@class, 'dropdown-container')]"
                                "//ul//li[contains(@class, 'alt-menu')]//a[@href] | "
                                "//a[@href]",
                            )
                            print(f"    Found {len(new_links)} total links after hover")

                            for link in new_links:
                                try:
                                    if not link.is_displayed():
                                        continue

                                    href = link.get_attribute("href")
                                    text = link.text.strip()

                                    # Skip excluded links
                                    if text in excluded_texts:
                                        continue

                                    if href and href not in ["#", "", None, "javascript:void(0)"]:
                                        full_url = urljoin(base_url, href)

                                        # Skip excluded URLs
                                        if full_url in excluded_urls:
                                            continue

                                        # Skip base URL
                                        if full_url == base_url or full_url == base_url.rstrip("/"):
                                            continue

                                        if text:
                                            # Path includes nested item text
                                            current_path = base_path + [nested_text]
                                            path_tuple = tuple(current_path)
                                            all_links.add((text, full_url, path_tuple))
                                            print(
                                                "      ✓ Added from nested hover: "
                                                f"{text}: {full_url} "
                                                f"(Path: {' --> '.join(path_tuple)})"
                                            )
                                except Exception:
                                    continue

                            # Move back to parent
                            actions.move_to_element(mevzuat_item).perform()
                            time.sleep(0.8)
                        except Exception as e:
                            print(f"    Error hovering over nested item: {e}")
                            try:
                                actions.move_to_element(mevzuat_item).perform()
                                time.sleep(0.5)
                            except Exception:
                                pass
                            continue
                except Exception as e:
                    print(f"  Error processing nested items: {e}")
                    import traceback

                    traceback.print_exc()
            except Exception as e:
                print(f"  Error in fallback: {e}")
                import traceback

                traceback.print_exc()

        except Exception as e:
            print(f"  Error processing '{TARGET_TEXT}': {e}")
            import traceback

            traceback.print_exc()

        # Final filtering: Remove any excluded links that might have slipped through
        excluded_texts = ["Anasayfa", "RSS", "S.S.S", "İletişim", "Home", "Contact", "EN", "TR"]
        excluded_urls = [
            base_url,
            base_url.rstrip("/"),
            "https://ttkb.meb.gov.tr/meb_iys_dosyalar/index.html",
        ]

        print(f"\nBefore final filtering: {len(all_links)} links")

        filtered_links = []
        for text, url, path in sorted(all_links):
            # Skip excluded links
            if text in excluded_texts:
                print(f"  Filtered out by text: {text}")
                continue
            if url in excluded_urls:
                print(f"  Filtered out by URL: {url}")
                continue
            if url == base_url or url == base_url.rstrip("/"):
                print(f"  Filtered out base URL: {url}")
                continue
            filtered_links.append({"text": text, "url": url, "path": list(path)})

        print(f"After final filtering: {len(filtered_links)} links")
        links_found = filtered_links

        print(f"\n{'='*60}")
        print(f"Found {len(links_found)} total links in dropdown menus:")
        for i, link in enumerate(links_found, 1):
            print(f"{i}. {link['text']}: {link['url']}")

    except Exception as e:
        print(f"Error occurred: {e}")
        import traceback

        traceback.print_exc()

    finally:
        driver.quit()

    return links_found


def upload_links_to_s3(links, bucket_name, object_key):
    try:
        import boto3
    except ModuleNotFoundError:
        print("boto3 is not installed; skipping S3 upload.")
        return False

    try:
        s3_client = boto3.client("s3")
        payload = json.dumps(links, ensure_ascii=False, indent=2)
        s3_client.put_object(
            Bucket=bucket_name,
            Key=object_key,
            Body=payload.encode("utf-8"),
            ContentType="application/json; charset=utf-8",
        )
        print(f"Uploaded JSON output to s3://{bucket_name}/{object_key}")
        return True
    except Exception as exc:
        print(f"Failed to upload JSON to S3: {exc}")
        return False


if __name__ == "__main__":
    print(f"Starting scraper for MEB TTKB '{TARGET_TEXT}' dropdown links...")
    print("=" * 60)

    links = scrape_mevzuat_kys_links()

    print("\n" + "=" * 60)
    print(f"Total links found: {len(links)}")

    # Save to JSON file
    output_file = "mevzuat_kys_links.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(links, f, ensure_ascii=False, indent=2)

    print(f"\nLinks saved to {output_file}")

    upload_links_to_s3(links, S3_BUCKET_NAME, S3_OUTPUT_KEY)

    # Also print JSON output
    # print("\nJSON Output:")
    # print(json.dumps(links, ensure_ascii=False, indent=2))