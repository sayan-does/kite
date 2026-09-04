import resend

from app.config import settings

resend.api_key = settings.EMAIL_API_KEY


def _build_html_digest(items: list) -> str:
    rows = []
    for item in items:
        if item["type"] == "article":
            link_html = ""
            if item.get("url"):
                link_html = f'<br><a href="{item["url"]}" style="color:#0369a1;font-size:13px">Read source</a>'
            rows.append(
                f'<tr><td style="padding:12px;border-bottom:1px solid #eee">'
                f'<strong style="font-size:16px">{item["title"]}</strong><br>'
                f'<span style="color:#666">{item["summary"]}</span>'
                f'{link_html}'
                f'<br><span style="color:#999;font-size:12px">Discovery Article</span>'
                f'</td></tr>'
            )
        elif item["type"] == "dependency_update":
            rows.append(
                f'<tr><td style="padding:12px;border-bottom:1px solid #eee">'
                f'<strong>{item["package_name"]} v{item["version"]}</strong> '
                f'<span style="display:inline-block;padding:2px 8px;border-radius:4px;'
                f'font-size:12px;background:#e0f2fe;color:#0369a1">'
                f'{item["update_type"]}</span><br>'
                f'<span style="color:#666">{item["summary"]}</span>'
                f'</td></tr>'
            )

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:600px;margin:0 auto;padding:20px">
<h2 style="color:#333">Your Kite Daily Digest</h2>
<table style="width:100%;border-collapse:collapse">
{''.join(rows)}
</table>
<p style="color:#999;font-size:12px;margin-top:20px">Kite — your personal tech radar</p>
</body>
</html>"""


async def send_digest(user_email: str, items: list) -> dict:
    html = _build_html_digest(items)
    params = {
        "from": settings.EMAIL_FROM,
        "to": [user_email],
        "subject": "Your Kite Daily Digest",
        "html": html,
    }
    return resend.Emails.send(params)
