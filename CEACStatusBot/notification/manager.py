import json
import os
import datetime

import pytz

from CEACStatusBot.captcha import CaptchaHandle, OnnxCaptchaHandle
from CEACStatusBot.request import query_status

from .handle import NotificationHandle

DEFAULT_ACTIVE_HOURS = "00:00-23:59"


class NotificationManager:
    def __init__(
        self,
        location: str,
        number: str,
        passport_number: str,
        surname: str,
        captchaHandle: CaptchaHandle = OnnxCaptchaHandle("captcha.onnx"),
    ) -> None:
        self.__handleList = []
        self.__location = location
        self.__number = number
        self.__captchaHandle = captchaHandle
        self.__passport_number = passport_number
        self.__surname = surname
        self.__status_file = "status_record.json"

    def _get_hour_range(self) -> list:
        active_hours = os.getenv("ACTIVE_HOURS")
        if active_hours is None:
            active_hours = DEFAULT_ACTIVE_HOURS
        start_str, end_str = active_hours.split("-")
        start = datetime.datetime.strptime(start_str, "%H:%M").time()
        end = datetime.datetime.strptime(end_str, "%H:%M").time()
        if start > end:
            raise ValueError("Start time must be before end time, got start: {start}, end: {end}")
        return start, end

    def addHandle(self, notificationHandle: NotificationHandle) -> None:
        self.__handleList.append(notificationHandle)

    def send(self) -> None:
        # Single-shot status fetch; no retry to reduce CEAC request pressure.
        res = query_status(
            self.__location,
            self.__number,
            self.__passport_number,
            self.__surname,
            self.__captchaHandle,
        )
        # Avoid sending when the status fetch fails or is incomplete.
        if not res.get("success"):
            # Surface error details to help diagnose CEAC response changes or captcha failures.
            print(f"Status query failed; skip notification. error={res.get('error')}")
            return
        current_status = res["status"]
        current_last_updated = res["case_last_updated"]
        print(f"Current status: {current_status} - Last updated: {current_last_updated}")
        # Load the previous statuses from the file.
        statuses = self.__load_statuses()

        # Determine whether to send: change detected or last send older than 24 hours.
        should_send = False
        if not statuses:
            should_send = True
        else:
            last_record = statuses[-1]
            if current_status != last_record.get("status", None) or current_last_updated != last_record.get("last_updated", None):
                should_send = True
            else:
                last_sent_str = last_record.get("last_sent") or last_record.get("date")
                last_sent_dt = self.__parse_iso_datetime(last_sent_str)
                if last_sent_dt:
                    hours_since_last_send = (self.__now_local() - last_sent_dt).total_seconds() / 3600.0
                    if hours_since_last_send >= 24:
                        should_send = True

        if should_send:
            self.__save_current_status(current_status, current_last_updated)
            self.__send_notifications(res)
        else:
            print("Status unchanged. No notification sent.")

    def __load_statuses(self) -> list:
        if os.path.exists(self.__status_file):
            with open(self.__status_file, "r") as file:
                return json.load(file).get("statuses", [])
        return []

    def __save_current_status(self, status: str, last_updated: str) -> None:
        statuses = self.__load_statuses()
        # Track when we sent the notification to enforce a 24-hour resend window.
        statuses.append({
            "status": status,
            "last_updated": last_updated,
            "date": datetime.datetime.now().isoformat(),
            "last_sent": self.__now_local().isoformat()
        })

        with open(self.__status_file, "w") as file:
            json.dump({"statuses": statuses}, file)

    def __send_notifications(self, res: dict) -> None:
        # Enrich payload for human-readable formatting in notification handles.
        res["days_since_last_updated"] = self.__days_since_last_updated(res.get("case_last_updated"))
        res["message_text"] = self.__format_message_text(res)
        if res["status"] == "Refused":
            localTimeZone = None
            try:
                TIMEZONE = os.environ["TIMEZONE"]
                localTimeZone = pytz.timezone(TIMEZONE)
                localTime = datetime.datetime.now(localTimeZone)
            except pytz.exceptions.UnknownTimeZoneError:
                print("UNKNOWN TIMEZONE Error, use default")
                localTime = datetime.datetime.now()
            except KeyError:
                print("TIMEZONE Error")
                localTime = datetime.datetime.now()

            active_hour_start, active_hour_end = self._get_hour_range()
            # Keep timezone info only when it is explicitly configured.
            start_dt = datetime.datetime.combine(localTime.date(), active_hour_start, tzinfo=localTimeZone)
            end_dt = datetime.datetime.combine(localTime.date(), active_hour_end, tzinfo=localTimeZone)
            if not (start_dt <= localTime <= end_dt):
                print(
                    f"Outside active hours {os.getenv('ACTIVE_HOURS', DEFAULT_ACTIVE_HOURS)}. "
                    "No notification sent for Refused status."
                )
                return

        for notificationHandle in self.__handleList:
            notificationHandle.send(res)

    def __now_local(self) -> datetime.datetime:
        # Use TIMEZONE if provided; fall back to local time for consistent timestamps.
        try:
            timezone_name = os.environ["TIMEZONE"]
            return datetime.datetime.now(pytz.timezone(timezone_name))
        except Exception:
            return datetime.datetime.now()

    def __parse_iso_datetime(self, value: str) -> datetime.datetime | None:
        # Parse stored ISO strings without failing the notification flow.
        if not value:
            return None
        try:
            return datetime.datetime.fromisoformat(value)
        except ValueError:
            return None

    def __days_since_last_updated(self, case_last_updated: str) -> int | None:
        # CEAC uses "19-Oct-2022" style; compute days since that date.
        if not case_last_updated:
            return None
        try:
            last_updated_date = datetime.datetime.strptime(case_last_updated, "%d-%b-%Y").date()
        except ValueError:
            return None
        return (self.__now_local().date() - last_updated_date).days

    def __format_message_text(self, res: dict) -> str:
        # Use a simple text layout for email/Telegram instead of raw JSON.
        days_text = "N/A"
        if res.get("days_since_last_updated") is not None:
            days_text = f"{res['days_since_last_updated']} day(s)"
        return "\n".join([
            "CEAC Status Update",
            f"Case: {res.get('application_num_origin', '')}",
            f"Status: {res.get('status', '')}",
            f"Visa Type: {res.get('visa_type', '')}",
            f"Case Created: {res.get('case_created', '')}",
            f"Last Updated: {res.get('case_last_updated', '')} ({days_text} ago)",
            f"Checked At: {res.get('time', '')}",
            f"Description: {res.get('description', '')}",
        ])
