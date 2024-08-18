import requests
from bs4 import BeautifulSoup, ResultSet, Tag, PageElement
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
import time
import re
from datetime import datetime
import pytz
from ics import Calendar, Event
from datetime import datetime

def setup_driver(driver: webdriver.Safari):

    # Open a page to set cookies
    driver.get("https://cbase.som.sunysb.edu/conet/calendar/calendarFrame.cfm")

    # Clear all cookies before setting new ones
    driver.delete_all_cookies()
    
    # Set cookies
    cookies = [
        {'name': 'CFID', 'value': '14226153'},
        {'name': 'CFTOKEN', 'value': '92151554'}
    ]
    for cookie in cookies:
        driver.add_cookie(cookie)

    return driver
    

def get_cal(month: str, driver: webdriver.Safari):
    
    # URL to scrape
    url = "https://cbase.som.sunysb.edu/conet/calendar/dynamicCalendar.cfm"
    
    # Navigate to the target URL
    driver.get(url)

    # Wait for the content to load
    WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.CSS_SELECTOR, 'body')))

    # Set month
    driver.execute_script(f"document.getElementsByName('tbSelMonth')[0].value = '{month}';")
    
    # Trigger the change event if needed
    driver.execute_script("document.getElementsByName('tbSelMonth')[0].dispatchEvent(new Event('change'));")
    time.sleep(2)
    driver.implicitly_wait(2)
    
    # Extract HTML content
    html = driver.page_source
    soup = BeautifulSoup(html, 'html.parser')

    return soup

def get_popup_details(href: str, driver: webdriver.Safari):

    original_window = driver.current_window_handle
    assert len(driver.window_handles) == 1
    element = driver.find_element(By.CSS_SELECTOR, f'a[href="{href}"]')

    element.click()
    driver.implicitly_wait(3)

    # Loop through until we find a new window handle
    for window_handle in driver.window_handles:
        if window_handle != original_window:
            driver.switch_to.window(window_handle)
            break

    driver.implicitly_wait(2)
    time.sleep(2)

    # Scrape the popup content
    popup_html = driver.page_source
    popup_soup: BeautifulSoup = BeautifulSoup(popup_html, 'html.parser')

    for sup_tag in popup_soup.find_all('sup'):
        sup_tag.unwrap() 
    
    tables: ResultSet[Tag] = popup_soup.select('table tbody')  # Select all tables with a tbody element
    section_data = []

    for table in tables:
        rows: ResultSet[PageElement] = table.find_all('tr')
        if len(rows) < 1:
            continue
        
        tds: ResultSet[PageElement] = rows[0].find_all('td')
        if len(tds) < 5:
            continue
        
        data_td: PageElement = tds[3]
        
        # Extract section title
        section_title: str = data_td.find(text=True, recursive=False).strip()
        
        ul: PageElement = data_td.find('ul')
        if not ul:
            continue
        
        section_info = {'section': section_title}
        
        for li in ul.find_all('li'):
            # Get the first child as the field name
            first_child = li.find(True, recursive=False)
            if first_child:
                field_name = first_child.get_text(strip=True).lower().rstrip(':')
                if field_name in ['time', 'instruction method', 'instructor', 'location', 'assignment', 'objective']:
                    # Use a helper function to extract the field value
                    field_value = extract_field_value(li)
                    section_info[field_name] = field_value
        
        if section_info:
            section_data.append(section_info)

    # Close the popup
    driver.close()

    #Switch back to the old tab or window
    driver.switch_to.window(original_window)
    
    return section_data

def extract_field_value(li_element):
    field_name_element = li_element.find(True, recursive=False)
    if field_name_element:
        field_name_element.extract()
    
    # Get all text from the <li> element and clean it
    all_text = li_element.get_text(separator=' ', strip=True)
    
    # Replace non-breaking spaces and other unwanted characters
    clean_text = all_text.replace('\xa0', ' ').replace('\u200b', '')  # Replace non-breaking space and zero-width space
    
    return clean_text

def create_event_list(soup: BeautifulSoup, month: str, year: str, driver: webdriver.Safari):
    timezone = pytz.timezone('America/New_York')
        
    # Get table (month)
    table_body = soup.select_one('body > form > table > tbody > tr:nth-child(2) > td > table > tbody')
    events = []

    # Iterate over days
    for cell in table_body.find_all('td', {'id': 'calCell'}):
        date = cell.find('font', {'id': 'calDateText'})
        if date:
            day = date.get_text(strip=True)

            # Iterate over classes
            for section in cell.find_all('table'):
                rows = section.find_all('tr')
                prev_event=None
                section_details = []
                #additional_details = {}
                for row in rows:
                    if not prev_event:
                        prev_event = row.find('font', {'color': '#0033FF'})
                        
                        # Extract the link to the popup (assuming the link is within this row)
                        link = row.find('a', href=True)
                        if link:
                            href = link['href']
                            
                            # Get additional details from the popup
                            popup_details = get_popup_details(href, driver)
                            
                            section_details.extend(popup_details)

                    else:
                        event_time = row.find('font', {'color': '#000000'})
                        event_name = prev_event.get_text(strip=True)
                        class_name = re.sub(r'^\*.\s*', '', event_name)
                        event_time = event_time.get_text(strip=True)

                        # Create date string
                        date_str = f"{day}-{month}-{year}"
                        date_format = "%d-%m-%Y"
                        date_obj = datetime.strptime(date_str, date_format)
                        
                        # Parse time range
                        if event_time == 'All Day':
                            continue

                        start_time_str, end_time_str = event_time.split('-')
                        start_time_obj = datetime.strptime(start_time_str.strip(), "%I:%M %p")
                        end_time_obj = datetime.strptime(end_time_str.strip(), "%I:%M %p")
                        
                        # Combine date with times
                        start_datetime = datetime.combine(date_obj.date(), start_time_obj.time())
                        end_datetime = datetime.combine(date_obj.date(), end_time_obj.time())
                        start_datetime = timezone.localize(start_datetime)
                        end_datetime = timezone.localize(end_datetime)


                        # Create event dict
                        events.append({
                            'start_datetime': start_datetime,
                            'end_datetime': end_datetime,
                            'name': class_name,
                            'details': section_details
                        })
                        prev_event=None
    print(len(events))
    return events

def event_to_cal(eventList: list[any]):

    calendar = Calendar()
    
    for event in eventList:
        e = Event()
        e.name = event['name']
        e.begin = event['start_datetime']
        e.end = event['end_datetime']

        # Optionally add details to the event description
        horizontal_line = '*' * 40
        if 'details' in event:
            details_lines = []
            for section in event['details']:
                section_lines = [f"{key.capitalize()}: {value}" for key, value in section.items()]
                section_description = "\n\n".join(section_lines)

                details_lines.append(section_description)
            
            description = f"\n\n\n{horizontal_line}\n\n\n".join(details_lines)
            e.description = description

        calendar.events.add(e)

    with open('classes.ics', 'w') as f:
        f.writelines(calendar)


def main():
    months: list[str] = ["8", "9", "10", "11", "12"]
    eventList: list[dict] = []

    driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()))

    driver = setup_driver(driver)
    
    for month in months:
        soup: BeautifulSoup = get_cal(month, driver)
        test: list[any] = create_event_list(soup, month, '2024', driver)
        eventList.extend(test)
    event_to_cal(eventList)

    driver.quit()

main()