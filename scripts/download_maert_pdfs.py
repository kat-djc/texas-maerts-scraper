import os
import time
import shutil
import glob
import logging
import tempfile
from io import StringIO
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException, WebDriverException, NoSuchElementException
from dotenv import load_dotenv
from PyPDF2 import PdfReader

# Load environment variables
load_dotenv()

# Constants
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE_DIR, '..', 'data', 'pdfs')
RNS_CSV_PATH = os.path.join(BASE_DIR, '..', 'data', "all_scraped_rns.csv")
DOWNLOAD_COUNTS_PATH = os.path.join(BASE_DIR, 'download_counts.csv')

os.makedirs(DATA_PATH, exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Helpers
def read_rn_numbers(csv_path):
    df = pd.read_csv(csv_path)
    return df['rn_number'].unique()

def wait_for_download(directory, timeout=30):
    seconds = 0
    while seconds < timeout:
        files = glob.glob(f"{directory}/*")
        if files:
            return max(files, key=os.path.getctime)
        time.sleep(1)
        seconds += 1
    return None

def validate_pdf(file_path):
    try:
        with open(file_path, 'rb') as f:
            PdfReader(f)
        return True
    except Exception as e:
        logging.warning(f"Invalid PDF detected: {file_path}. Error: {e}")
        return False

def init_driver(download_dir):
    options = webdriver.ChromeOptions()
    prefs = {"download.default_directory": download_dir, "plugins.always_open_pdf_externally": True}
    options.add_experimental_option("prefs", prefs)
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    driver = webdriver.Chrome(options=options)
    driver.implicitly_wait(5)
    return driver

def load_download_counts():
    if os.path.exists(DOWNLOAD_COUNTS_PATH):
        return pd.read_csv(DOWNLOAD_COUNTS_PATH)
    return pd.DataFrame(columns=['rn_number', 'download_counts'])

def update_download_counts(rn_number, count, df):
    if rn_number in df['rn_number'].values:
        df.loc[df['rn_number'] == rn_number, 'download_counts'] = count
    else:
        df = pd.concat([df, pd.DataFrame([{'rn_number': rn_number, 'download_counts': count}])], ignore_index=True)
    df.to_csv(DOWNLOAD_COUNTS_PATH, index=False)
    return df

def safe_click(driver, by, value, retries=3):
    for _ in range(retries):
        try:
            el = driver.find_element(by, value)
            el.click()
            return True
        except Exception as e:
            logging.warning(f"Retry clicking failed element: {e}")
            time.sleep(1)
    return False

def scrape_maert_for_rns(rn_numbers):
    download_counts_df = load_download_counts()

    for rn in rn_numbers:
        logging.info(f"Processing RN: {rn}")
        maert_download_count = 0

        try:
            existing_count = download_counts_df.loc[download_counts_df['rn_number'] == rn, 'download_counts'].fillna(0).values
            existing_count = existing_count[0] if len(existing_count) > 0 else 0

            with tempfile.TemporaryDirectory() as tmp_dir:
                driver = init_driver(tmp_dir)
                driver.get("https://records.tceq.texas.gov/cs/idcplg?IdcService=TCEQ_SEARCH")

                Select(driver.find_element(By.ID, 'xRecordSeries')).select_by_value('1081')
                Select(driver.find_element(By.ID, 'xInsightDocumentType')).select_by_value('27')
                Select(driver.find_element(By.XPATH, '/html/body/table[1]/tbody/tr[5]/td/table/tbody/tr/td/div/form/table/tbody/tr[4]/td/table/tbody/tr[1]/td[1]/select')).select_by_value('xRefNumTxt')
                driver.find_element(By.XPATH, '/html/body/table[1]/tbody/tr[5]/td/table/tbody/tr/td/div/form/table/tbody/tr[4]/td/table/tbody/tr[1]/td[2]/input').send_keys(rn)
                safe_click(driver, By.XPATH, "/html/body/table[1]/tbody/tr[5]/td/table/tbody/tr/td/div/form/table/tbody/tr[4]/td/table/tbody/tr[5]/td[3]/div/button[1]")

                while True:
                    safe_click(driver, By.XPATH, "//a[contains(@href, \"addQueryFilter('xItemType', '1')\")]")
                    time.sleep(2)

                    try:
                        dfs = pd.read_html(StringIO(driver.page_source))
                        table = dfs[4]
                        maerts = table[table[12] == 'MAERT']
                    except Exception as e:
                        logging.warning(f"Table parsing failed: {e}")
                        break

                    for hyperlink, permit_number, date in zip(maerts[2], maerts[6], maerts[16]):
                        try:
                            logging.info(f"Attempting to download: {permit_number} for RN {rn}")
                            safe_click(driver, By.LINK_TEXT, hyperlink)
                            downloaded = wait_for_download(tmp_dir)

                            if downloaded and validate_pdf(downloaded):
                                unique_id = int(time.time())
                                formatted_date = date.split(" ")[0].replace("/", "-")
                                final_path = os.path.join(DATA_PATH, f"{rn}_{permit_number}_{formatted_date}_{unique_id}.pdf")
                                shutil.move(downloaded, final_path)
                                logging.info(f"Downloaded to {final_path}")
                                maert_download_count += 1
                            else:
                                logging.warning(f"Invalid or missing PDF for {permit_number}")

                        except Exception as download_err:
                            logging.warning(f"Download error for {permit_number}: {download_err}")

                    try:
                        next_button = driver.find_element(By.XPATH, "/html/body/table[1]/tbody/tr[5]/td/table/tbody/tr/td/div/div[2]/table/tbody/tr/td[5]/a")
                        next_button.click()
                        time.sleep(2)
                    except NoSuchElementException:
                        logging.info("No more pages.")
                        break

                driver.quit()
                download_counts_df = update_download_counts(rn, existing_count + maert_download_count, download_counts_df)

        except Exception as e:
            logging.error(f"Error processing RN {rn}: {e}")

# Main entry
if __name__ == "__main__":
    rns = read_rn_numbers(RNS_CSV_PATH)
    scrape_maert_for_rns(rns)
