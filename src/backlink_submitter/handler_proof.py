"""Runtime-bound handlers, not unrelated endpoint strings in a bundle."""

import hashlib
import re
from urllib.parse import urljoin, urlparse


async def bound_submit_handlers(page, form):
    """Inspect native listeners on the form/ancestors and actual hydrated React props."""
    tag = "backlinkInspectionForm"
    await form.evaluate("(e,k)=>{globalThis[k]=e}", tag)
    session = await page.context.new_cdp_session(page)
    handlers = []
    try:
        value = await session.send(
            "Runtime.evaluate",
            {
                "expression": "[globalThis.backlinkInspectionForm,...(()=>{let n=globalThis.backlinkInspectionForm.parentNode,a=[];while(n){a.push(n);n=n.parentNode}return a})(),window]",
                "objectGroup": "backlink-handler-proof",
            },
        )
        props = await session.send(
            "Runtime.getProperties", {"objectId": value["result"]["objectId"], "ownProperties": True}
        )
        for prop in props["result"]:
            if not prop["name"].isdigit():
                continue
            oid = prop["value"].get("objectId")
            listeners = await session.send("DOMDebugger.getEventListeners", {"objectId": oid})
            for listener in listeners["listeners"]:
                if listener["type"] != "submit":
                    continue
                handler = listener.get("originalHandler", listener.get("handler", {})).get("objectId")
                if not handler:
                    return None
                body = await session.send(
                    "Runtime.callFunctionOn",
                    {
                        "objectId": handler,
                        "functionDeclaration": "function(){return Function.prototype.toString.call(this)}",
                        "returnByValue": True,
                    },
                )
                handlers.append(body["result"].get("value", ""))
        react = await form.evaluate(
            """e=>{let h=[];for(let n=e;n;n=n.parentElement){for(const k of Object.keys(n)){if(k.startsWith('__reactProps$')&&n[k].onSubmit)h.push(Function.prototype.toString.call(n[k].onSubmit))}}return h}"""
        )
        # React's delegation wrapper is not a dispatch proof; the actual form onSubmit is.
        if react:
            return react
        return handlers
    finally:
        await session.send("Runtime.releaseObjectGroup", {"objectGroup": "backlink-handler-proof"})
        await session.detach()
        await page.evaluate("(k)=>{delete globalThis[k]}", tag)


def matcher_from_handler(handler, source_url, domain):
    """A bound submit listener with one statically literal write call, plus preventDefault."""
    if "preventDefault" not in handler:
        return None
    calls = re.findall(
        r"fetch\(\s*[\'\"]([^\'\"]+)[\'\"]\s*,\s*\{[^{}]*?method\s*:\s*[\'\"](POST|PUT|PATCH)[\'\"]", handler, re.S
    )
    calls += [
        (u, m) for m, u in re.findall(r"\.open\(\s*[\'\"](POST|PUT|PATCH)[\'\"]\s*,\s*[\'\"]([^\'\"]+)[\'\"]", handler)
    ]
    if len(calls) != 1 or len(re.findall(r"\bfetch\(|\.open\(", handler)) != 1:
        return None
    url = urljoin(source_url, calls[0][0])
    p = urlparse(url)
    if (
        p.scheme != "https"
        or (p.hostname or "").removeprefix("www.") != domain.removeprefix("www.")
        or p.query
        or p.fragment
        or p.username
        or p.password
    ):
        return None
    return {"method": calls[0][1], "host": p.hostname, "path": p.path or "/", "verified": True}, {
        "kind": "runtime_bound_submit_handler",
        "source_url": source_url,
        "handler_sha256": hashlib.sha256(handler.encode()).hexdigest(),
    }
