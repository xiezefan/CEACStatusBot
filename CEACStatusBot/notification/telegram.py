import requests
import json
from .handle import NotificationHandle

class TelegramNotificationHandle(NotificationHandle):
    def __init__(self, bot_token: str, chat_id: str) -> None:
        super().__init__()
        self.__bot_token = bot_token
        self.__chat_id = chat_id
        self.__api_url = f"https://api.telegram.org/bot{self.__bot_token}/sendMessage"

    def send(self, result):
        # {'success': True, 'visa_type': 'NONIMMIGRANT VISA APPLICATION', 'status': 'Issued', 'case_created': '30-Aug-2022', 'case_last_updated': '19-Oct-2022', 'description': 'Your visa is in final processing. If you have not received it in more than 10 working days, please see the webpage for contact information of the embassy or consulate where you submitted your application.', 'application_num': '***'}

        # Telegram MarkdownV2 requires escaping special characters.
        def escape_md(text: str) -> str:
            specials = r"_*[]()~`>#+-=|{}.!"
            return "".join("\\" + ch if ch in specials else ch for ch in text)

        message_title = f"[CEACStatusBot] {result['application_num_origin']}: {result['status']}"
        days_text = "N/A"
        if result.get("days_since_last_updated") is not None:
            days_text = f"{result['days_since_last_updated']} day(s)"
        # Build a concise Markdown message without Description.
        message_content = "\n".join([
            f"*Case:* {result.get('application_num_origin', '')}",
            f"*Status:* {result.get('status', '')}",
            f"*Visa Type:* {result.get('visa_type', '')}",
            f"*Case Created:* {result.get('case_created', '')}",
            f"*Last Updated:* {result.get('case_last_updated', '')} ({days_text} ago)",
            f"*Checked At:* {result.get('time', '')}",
        ])
        message_title = escape_md(message_title)
        message_content = escape_md(message_content)

        # Construct the message text with the title in bold
        message_text = f"*{message_title}*\n\n{message_content}"

        # Send the message using the Telegram Bot API
        response = requests.post(self.__api_url, data={
            "chat_id": self.__chat_id,
            "text": message_text,
            "parse_mode": "MarkdownV2"
        })

        # Check the response
        if response.status_code == 200:
            print("Message sent successfully")
        else:
            print(f"Failed to send message: {response.text}")
