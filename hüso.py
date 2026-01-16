import time
import json
import os
import requests
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- AYARLAR ---
TARGET_KEYWORD = "Mevzuat"
BASE_URL = "https://ttkb.meb.gov.tr/"
OUTPUT_FILE = "ttkb_mevzuat_full_data.json"

# --- YARDIMCI FONKSİYONLAR ---

def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver

def clean_text(text):
    if not text: return ""
    return " ".join(text.split()).strip()

def get_data_type(url):
    """URL uzantısına göre dosya türünü belirler."""
    parsed = urlparse(url)
    path = parsed.path.lower()
    ext = os.path.splitext(path)[1]
    
    if ext == '.pdf': return 'PDF'
    if ext in ['.doc', '.docx']: return 'DOC'
    if ext in ['.xls', '.xlsx']: return 'EXCEL'
    if ext in ['.zip', '.rar']: return 'ARCHIVE'
    # Uzantı yoksa HTML kabul et
    return 'HTML'

def get_breadcrumb_path_list(element, root_element):
    """
    Elementten yukarı çıkarak hiyerarşiyi LİSTE olarak döndürür.
    """
    path = []
    current = element.parent
    
    # Kök elemente kadar tırman
    while current and current != root_element:
        # Strateji 1: Ebeveyn 'ul' ise başlık genelde önceki kardeştir
        if current.name == 'ul':
            prev = current.find_previous_sibling()
            if prev and prev.name in ['span', 'a', 'div']:
                text = clean_text(prev.get_text())
                if text and text not in path:
                    path.insert(0, text)
        
        # Strateji 2: Ebeveyn 'li' ise başlık kendi içindeki text olabilir
        if current.name == 'li':
            # Link olmayan doğrudan metinleri veya spanları kontrol et
            direct_text = ""
            for child in current.find_all(['span', 'a'], recursive=False):
                # Kendi href'i yoksa veya # ise başlıktır
                if child != element and (not child.has_attr('href') or child['href'] in ['#', '']):
                    direct_text = clean_text(child.get_text())
                    break
            
            if direct_text and direct_text not in path:
                path.insert(0, direct_text)

        current = current.parent
    
    # En başa ana kategoriyi ekleyelim (Eğer yoksa)
    if not path or path[0] != "Mevzuat - KYS":
        path.insert(0, "Mevzuat - KYS")
        
    return path

# --- PHASE 1: MENÜ TARAMA (SELENIUM) ---

def scrape_menu_links():
    driver = setup_driver()
    menu_items = []
    
    try:
        print(f"1. Siteye gidiliyor: {BASE_URL}")
        driver.get(BASE_URL)
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        time.sleep(3)
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        print("2. Ana menü kapsayıcısı aranıyor...")
        target_li = None
        
        # Senin kodundaki li bulma mantığı
        candidates = soup.find_all('li')
        for li in candidates:
            txt = clean_text(li.get_text())
            if TARGET_KEYWORD in txt and "KYS" in txt:
                target_li = li
                print(f"   -> Kapsayıcı bulundu! (Text: {txt[:30]}...)")
                break
        
        if not target_li:
            print("HATA: Mevzuat kapsayıcısı bulunamadı.")
            return []

        print("3. Linkler ve Hiyerarşi Ayrıştırılıyor...")
        # Recursive=True ile derinlemesine tüm linkleri alıyoruz
        all_links = target_li.find_all('a', href=True)
        
        for link in all_links:
            href = link['href']
            text = clean_text(link.get_text())
            
            # Temel filtreler
            if not text: continue
            if href in ['#', 'javascript:void(0)', '']: continue
            if "Mevzuat - KYS" in text: continue 
            
            full_url = urljoin(BASE_URL, href)
            
            # Path'i liste olarak al
            path_list = get_breadcrumb_path_list(link, target_li)
            data_type = get_data_type(full_url)
            
            item = {
                "text": text,
                "url": full_url,
                "path_list": path_list,             # Liste formatı
                "path_string": " > ".join(path_list), # Okunabilir format
                "data_type": data_type,
                "source": "MENU"
            }
            
            # Tekrarı önle
            if not any(x['url'] == full_url for x in menu_items):
                menu_items.append(item)
                print(f"  [MENÜ] {data_type} | {text}")

    except Exception as e:
        print(f"Hata: {e}")
    finally:
        driver.quit()
        
    return menu_items

# --- PHASE 2: İÇERİK SAYFASI TARAMA (REQUESTS) ---

def scrape_content_page(parent_item):
    """HTML sayfasına gider ve içindeki dosya linklerini çeker."""
    url = parent_item['url']
    parent_path = parent_item['path_list']
    found_files = []
    
    try:
        # Requests ile hızlıca çekiyoruz
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        resp = requests.get(url, headers=headers, timeout=10)
        
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.content, 'html.parser')
            
            # İçerik alanını bul (TTKB sitesi için genelde 'icerik' id'si kullanılır)
            content_div = soup.find('div', id='icerik') or soup.find('div', class_='icerik') or soup.body
            
            links = content_div.find_all('a', href=True)
            for link in links:
                href = link['href']
                text = clean_text(link.get_text())
                full_url = urljoin(url, href)
                dtype = get_data_type(full_url)
                
                # Sadece dosya olanları al (HTML sayfalarını tekrar alırsak döngüye gireriz)
                if dtype != 'HTML':
                    if not text: text = os.path.basename(full_url)
                    
                    # Yeni path: Mevcut Path + Dosya Adı
                    new_path = parent_path + [text]
                    
                    file_item = {
                        "text": text,
                        "url": full_url,
                        "path_list": new_path,
                        "path_string": " > ".join(new_path),
                        "data_type": dtype,
                        "source": "PAGE_CONTENT"
                    }
                    found_files.append(file_item)
                    print(f"    -> [SAYFA İÇİ] {dtype} | {text}")
                    
    except Exception as e:
        print(f"    Hata ({url}): {e}")
        
    return found_files

# --- ANA ÇALIŞTIRMA ---

if __name__ == "__main__":
    print("=== AŞAMA 1: MENÜ TARAMA BAŞLIYOR ===")
    all_data = scrape_menu_links()
    
    print(f"\n[Aşama 1 Bitti] Menüden {len(all_data)} öğe bulundu.")
    
    final_results = []
    
    print("\n=== AŞAMA 2: DETAYLI DOSYA TARAMA BAŞLIYOR ===")
    for item in all_data:
        # Öğeyi ana listeye ekle
        final_results.append(item)
        
        # Eğer bu bir HTML sayfası ise içine girip dosya var mı bak
        if item['data_type'] == 'HTML' and "meb.gov.tr" in item['url']:
            print(f"  İnceleniyor: {item['text']}")
            sub_files = scrape_content_page(item)
            if sub_files:
                final_results.extend(sub_files)
    
    print("\n" + "="*50)
    print(f"TOPLAM SONUÇ: {len(final_results)}")
    
    # Kayıt
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(final_results, f, ensure_ascii=False, indent=2)
    print(f"Veriler '{OUTPUT_FILE}' dosyasına kaydedildi.")