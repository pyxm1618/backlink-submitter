"""Bounded corrections of confirmed server validation rejection; fixtures only."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from test_contracts import SheetAPI, submit_args

from backlink_submitter import contracts, sheets

DISPATCH = {"method": "POST", "host": "site.example", "path": "/api/submissions"}


def test_corrected_chinese_submission_is_pending_only_after_dispatch():
    result = contracts.classify("", "WYRPlay 待审核", submitted=True)
    assert result["status"] == "审核中"
    contracts.validate_outcome(result)
    assert contracts.classify("", "WYRPlay 待审核", submitted=False)["status"] == "待提交"
    assert contracts.classify("WYRPlay 待审核", "WYRPlay 待审核", submitted=True)["status"] == "需人工核查"


class DispatchPage:
    def on(self, name, callback):
        self.callback = callback

    def remove_listener(self, name, callback):
        self.callback = None


def send(path, *, attempts="", correction=False):
    page = DispatchPage()

    async def click():
        page.callback(SimpleNamespace(method="POST", url="https://site.example/api/submissions"))

    return asyncio.run(
        contracts.submit_once(
            **submit_args(
                path,
                click,
                backlink_id="site.example",
                prior_attempts=attempts,
                page=page,
                submission_request={"verified": True, **DISPATCH},
                validation_correction=correction,
            )
        )
    )


def reject(path):
    contracts.record_validation_rejection(
        path,
        message="标签不能超过5个！",
        response_dispatch=DISPATCH,
        request_not_accepted=True,
        acceptance_evidence=False,
    )


def test_validation_correction_preserves_attempt_and_increments_second_post(tmp_path):
    root = tmp_path / "intent.json"
    assert send(root) == 1
    api = SheetAPI()
    result = {"status": "提交失败", "evidence_code": "", "result_url": ""}
    sheets.write_outcome(
        api,
        2,
        "site.example",
        result,
        reason="标签校验失败",
        summary="fixture",
        attempt_increment=1,
        attempt_receipt=root,
    )
    reject(root)
    assert api.row[4] == "1"
    assert send(root, attempts="1", correction=True) == 1
    retry = root.with_suffix(".validation-retry-1.json")
    sheets.write_outcome(
        api, 2, "site.example", result, reason="fixture", summary="fixture", attempt_increment=1, attempt_receipt=retry
    )
    assert api.row[4] == "2"
    assert json.loads(root.read_text())["attempt_increment"] == 1
    with pytest.raises(ValueError):
        send(root, attempts="2", correction=True)
    assert api.row[4] == "2"


@pytest.mark.parametrize(
    "state", ["SUBMIT_RESULT_UNCONFIRMED", "SUBMIT_DISPATCH_UNCONFIRMED", "PAGE_PENDING", "ACCEPTED"]
)
def test_unknown_pending_accepted_cannot_retry(tmp_path, state):
    root = tmp_path / "intent.json"
    send(root)
    receipt = json.loads(root.read_text())
    receipt["state"] = state
    root.write_text(json.dumps(receipt))
    with pytest.raises(ValueError):
        send(root, attempts="1", correction=True)
    assert not root.with_suffix(".validation-retry-1.json").exists()


def test_validation_corrections_stop_after_two_and_wrong_attempt_fails(tmp_path):
    root = tmp_path / "intent.json"
    send(root)
    reject(root)
    with pytest.raises(ValueError):
        send(root, attempts="0", correction=True)
    send(root, attempts="1", correction=True)
    reject(root.with_suffix(".validation-retry-1.json"))
    send(root, attempts="2", correction=True)
    reject(root.with_suffix(".validation-retry-2.json"))
    with pytest.raises(ValueError):
        send(root, attempts="3", correction=True)
    assert len(list(tmp_path.glob("*.json"))) == 3


def test_retry_receipt_cannot_be_used_as_a_new_root(tmp_path):
    root = tmp_path / "intent.json"
    send(root)
    reject(root)
    send(root, attempts="1", correction=True)
    retry = root.with_suffix(".validation-retry-1.json")
    reject(retry)
    with pytest.raises(ValueError):
        send(retry, attempts="2", correction=True)


def test_acceptance_proof_blocks_rejection_recording(tmp_path):
    root = tmp_path / "intent.json"
    send(root)
    receipt = json.loads(root.read_text())
    receipt["proof"] = {"evidence_code": "E1", "dom_evidence": ["pending review"]}
    root.write_text(json.dumps(receipt))
    with pytest.raises(ValueError):
        reject(root)


@pytest.mark.parametrize("not_accepted,acceptance", [(False, False), (True, True), (None, False), (True, None)])
def test_rejection_requires_explicit_nonacceptance_and_no_acceptance(tmp_path, not_accepted, acceptance):
    root = tmp_path / "intent.json"
    send(root)
    with pytest.raises(ValueError):
        contracts.record_validation_rejection(
            root,
            message="标签不能超过5个！",
            response_dispatch=DISPATCH,
            request_not_accepted=not_accepted,
            acceptance_evidence=acceptance,
        )
    assert json.loads(root.read_text())["state"] == "SUBMIT_RESULT_UNCONFIRMED"
