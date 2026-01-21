import os
import requests
from bs4 import BeautifulSoup
import time

from CEACStatusBot.captcha import CaptchaHandle, OnnxCaptchaHandle

def query_status(location, application_num, passport_number, surname, captchaHandle: CaptchaHandle = OnnxCaptchaHandle("captcha.onnx")):
    # No retries here to avoid triggering CEAC anti-bot throttling.
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/105.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "en,zh-CN;q=0.9,zh;q=0.8",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "Host": "ceac.state.gov",
    }

    session = requests.Session()
    ROOT = "https://ceac.state.gov"

    try:
        r = session.get(url=f"{ROOT}/ceacstattracker/status.aspx?App=NIV", headers=headers)
    except Exception as e:
        print(e)
        return {"success": False, "error": f"GET status page failed: {e}"}
    print(f"Status page response: {r.status_code}, bytes={len(r.text)}")
    # Full HTML dump for debugging when CEAC changes page structure.
    print("Status page full response:")
    print(r.text)

    def extract_update_panel_html(response_text: str, panel_id: str) -> str | None:
        # ASP.NET async postback format: ...|updatePanel|<panel_id>|<html>|
        if "updatePanel" not in response_text:
            return None
        parts = response_text.split("|")
        for i, part in enumerate(parts):
            if part == "updatePanel" and i + 2 < len(parts):
                if parts[i + 1] == panel_id:
                    return parts[i + 2]
        return None

    soup = BeautifulSoup(r.text, features="lxml")

    # Find captcha image
    captcha = soup.find(name="img", id="c_status_ctl00_contentplaceholder1_defaultcaptcha_CaptchaImage")
    if not captcha or not captcha.get("src"):
        print("Captcha image tag not found or missing src.")
        return {"success": False, "error": "Captcha image tag not found"}
    image_url = ROOT + captcha["src"]
    try:
        img_resp = session.get(image_url)
    except Exception as e:
        print(e)
        return {"success": False, "error": f"GET captcha image failed: {e}"}
    print(f"Captcha image response: {img_resp.status_code}, bytes={len(img_resp.content)}")

    # Resolve captcha
    captcha_num = captchaHandle.solve(img_resp.content)
    print(f"Captcha solved: {captcha_num}")

    # Find the correct value for the location dropdown
    location_dropdown = soup.find("select", id="Location_Dropdown")
    if not location_dropdown:
        print("Location dropdown not found.")
        return {"success": False, "error": "Location dropdown not found"}
    location_value = None
    for option in location_dropdown.find_all("option"):
        if location in option.text:
            location_value = option["value"]
            break

    if not location_value:
        print("Location not found in dropdown options.")
        return {"success": False, "error": "Location not found in dropdown options"}

    # Fill form
    def update_from_current_page(cur_page, name, data):
        ele = cur_page.find(name="input", attrs={"name": name})
        if ele:
            data[name] = ele["value"]

    data = {
        "ctl00$ToolkitScriptManager1": "ctl00$ContentPlaceHolder1$UpdatePanel1|ctl00$ContentPlaceHolder1$btnSubmit",
        "ctl00_ToolkitScriptManager1_HiddenField": ";;AjaxControlToolkit, Version=4.1.40412.0, Culture=neutral, PublicKeyToken=28f01b0e84b6d53e:en-US:acfc7575-cdee-46af-964f-5d85d9cdcf92:de1feab2:f9cec9bc:a67c2700:f2c8e708:8613aea7:3202a5a2:ab09e3fe:87104b7c:be6fb298",
        "__EVENTTARGET": "ctl00$ContentPlaceHolder1$btnSubmit",
        "__EVENTARGUMENT": "",
        "__LASTFOCUS": "",
        "__VIEWSTATE": "8GJOG5GAuT1ex7KX3jakWssS08FPVm5hTO2feqUpJk8w5ukH4LG/o39O4OFGzy/f2XLN8uMeXUQBDwcO9rnn5hdlGUfb2IOmzeTofHrRNmB/hwsFyI4mEx0mf7YZo19g",
        "__VIEWSTATEGENERATOR": "DBF1011F",
        "__VIEWSTATEENCRYPTED": "",
        "ctl00$ContentPlaceHolder1$Visa_Application_Type": "NIV",
        "ctl00$ContentPlaceHolder1$Location_Dropdown": location_value,  # Use the correct value
        "ctl00$ContentPlaceHolder1$Visa_Case_Number": application_num,
        "ctl00$ContentPlaceHolder1$Captcha": captcha_num,
        "ctl00$ContentPlaceHolder1$Passport_Number": passport_number,
        "ctl00$ContentPlaceHolder1$Surname": surname,
        "LBD_VCID_c_status_ctl00_contentplaceholder1_defaultcaptcha": "a81747f3a56d4877bf16e1a5450fb944",
        "LBD_BackWorkaround_c_status_ctl00_contentplaceholder1_defaultcaptcha": "1",
        "__ASYNCPOST": "true",
    }

    fields_need_update = [
        "__VIEWSTATE",
        "__VIEWSTATEGENERATOR",
        "LBD_VCID_c_status_ctl00_contentplaceholder1_defaultcaptcha",
    ]
    for field in fields_need_update:
        update_from_current_page(soup, field, data)

    try:
        r = session.post(url=f"{ROOT}/ceacstattracker/status.aspx", headers=headers, data=data)
    except Exception as e:
        print(e)
        return {"success": False, "error": f"POST status form failed: {e}"}
    print(f"Status form response: {r.status_code}, bytes={len(r.text)}")
    # Full HTML dump for debugging when CEAC changes page structure.
    print("Status form full response:")
    print(r.text)

    panel_html = extract_update_panel_html(r.text, "ctl00_ContentPlaceHolder1_UpdatePanel1")
    if panel_html:
        print("Using updatePanel HTML for parsing.")
        soup = BeautifulSoup(panel_html, features="lxml")
    else:
        soup = BeautifulSoup(r.text, features="lxml")
    status_tag = soup.find("span", id="ctl00_ContentPlaceHolder1_ucApplicationStatusView_lblStatus")
    if not status_tag:
        # Dump full response to diagnose DOM changes.
        print("Status tag not found; full response follows.")
        print(r.text)
        return {"success": False, "error": "Status tag not found in response"}

    application_num_returned = soup.find("span", id="ctl00_ContentPlaceHolder1_ucApplicationStatusView_lblCaseNo").string
    assert application_num_returned == application_num
    status = status_tag.string
    visa_type = soup.find("span", id="ctl00_ContentPlaceHolder1_ucApplicationStatusView_lblAppName").string
    case_created = soup.find("span", id="ctl00_ContentPlaceHolder1_ucApplicationStatusView_lblSubmitDate").string
    case_last_updated = soup.find("span", id="ctl00_ContentPlaceHolder1_ucApplicationStatusView_lblStatusDate").string
    description = soup.find("span", id="ctl00_ContentPlaceHolder1_ucApplicationStatusView_lblMessage").string

    result = {
        "success": True,
        "time": str(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())),
        "visa_type": visa_type,
        "status": status,
        "case_created": case_created,
        "case_last_updated": case_last_updated,
        "description": description,
        "application_num": application_num_returned,
        "application_num_origin": application_num
    }
    return result
