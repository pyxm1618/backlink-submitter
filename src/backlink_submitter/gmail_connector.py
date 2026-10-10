"""Read-only adapter for an existing connected Gmail tool invoker; never a second OAuth."""

import asyncio
import base64
import json
from datetime import datetime, timezone

from .contracts import MemorySecret


def decoded_result(result):
    if result.get("isError"):
        raise ConnectionError("GMAIL_CONNECTOR_UNAVAILABLE")
    if result.get("structuredContent") is not None:
        return result["structuredContent"]
    texts = [c["text"] for c in result.get("content", []) if c.get("type") == "text"]
    if len(texts) != 1:
        raise ConnectionError("GMAIL_CONNECTOR_RESPONSE_UNCONFIRMED")
    return json.loads(texts[0])


def normalized_message(message):
    headers = {h["name"].casefold(): h["value"] for h in message.get("payload", {}).get("headers", [])}
    body = []

    def collect(part):
        if part.get("mimeType") in {"text/plain", "text/html"}:
            if part.get("content"):
                body.append(part["content"])
            elif part.get("body", {}).get("data"):
                encoded = part["body"]["data"]
                body.append(
                    base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode("utf-8", errors="strict")
                )
        for child in part.get("parts", []):
            collect(child)

    collect(message.get("payload", {}))
    return {
        "message_id": message["id"],
        "sender": headers.get("from", ""),
        "recipient": headers.get("to", ""),
        "subject": headers.get("subject", ""),
        "received_at": datetime.fromtimestamp(int(message["internalDate"]) / 1000, timezone.utc).isoformat(),
        "body": "\n".join(body),
    }


class ConnectedGmail:
    """The hosting caller supplies the already-connected tools; values remain in memory."""

    def __init__(self, invoke):
        self.invoke = invoke
        self.account_credentials: dict[str, MemorySecret] = {}
        self.account_emails: dict[str, str] = {}

    async def new_account_password(self, domain):
        from .contracts import MemorySecret

        reply = await self.invoke("new_account_password", {"domain": domain})
        value = reply.get("value")
        if not isinstance(value, str) or not value:
            raise ConnectionError("NEW_ACCOUNT_CREDENTIAL_UNAVAILABLE")
        secret = MemorySecret(value)
        self.account_credentials[domain] = secret
        email = reply.get("email")
        if isinstance(email, str) and "@" in email:
            self.account_emails[domain] = email
        return secret

    def platform_password(self, domain):
        """Only credentials created in this run; never an identity-provider password."""
        return self.account_credentials.get(domain)

    def platform_email(self, domain):
        return self.account_emails.get(domain)

    async def __call__(self, operation, arguments):
        if operation == "get_profile":
            profile = decoded_result(await self.invoke("gmail_get_profile", {}))
            return {"email": profile.get("emailAddress", profile.get("email", ""))}
        if operation != "search_messages":
            raise ValueError("Read-only Gmail operation unsupported")
        listing = decoded_result(await self.invoke("gmail_search_emails", arguments))
        items = listing.get("messages", listing.get("emails"))
        if not isinstance(items, list):
            raise ConnectionError("GMAIL_CONNECTOR_RESPONSE_UNCONFIRMED")
        messages = []
        for item in items:
            full = decoded_result(await self.invoke("gmail_read_email", {"message_id": item["id"], "format": "full"}))
            messages.append(normalized_message(full))
        return messages


_stdio_lock: asyncio.Lock | None = None


async def stdio_invoke(operation, arguments):
    import asyncio

    global _stdio_lock
    if _stdio_lock is None:
        _stdio_lock = asyncio.Lock()
    async with _stdio_lock:
        return await _stdio_exchange(operation, arguments)


async def _stdio_exchange(operation, arguments):
    """Host performs the existing connector call; replies travel on stdin, never disk."""
    import asyncio
    import sys

    if operation not in {"gmail_get_profile", "gmail_search_emails", "gmail_read_email", "new_account_password"}:
        raise ValueError("Unsupported host mail operation")
    request_key = "credential_request" if operation == "new_account_password" else "gmail_request"
    print(json.dumps({request_key: operation, "arguments": arguments}), flush=True)
    if sys.stdin.isatty():
        import termios

        settings = termios.tcgetattr(sys.stdin.fileno())
        settings[3] &= ~termios.ECHO
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSANOW, settings)
    reply = await asyncio.wait_for(asyncio.to_thread(sys.stdin.readline), 180)
    if not reply:
        raise ConnectionError("GMAIL_CONNECTOR_UNAVAILABLE")
    return json.loads(reply)
