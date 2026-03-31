"""
Tests for mainlayer_billing.py — BillingClient.
All Mainlayer API calls are mocked.
"""
import sys
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


@pytest.fixture
def mock_mainlayer_client():
    client = MagicMock()
    client.resources.verify_access = AsyncMock()
    client.resources.get_status = AsyncMock()
    return client


@pytest.fixture
def billing_client(mock_mainlayer_client):
    with patch("mainlayer_billing.MainlayerClient", return_value=mock_mainlayer_client):
        from mainlayer_billing import BillingClient
        return BillingClient(api_key="test-key")


@pytest.mark.asyncio
async def test_verify_access_authorized(billing_client, mock_mainlayer_client):
    mock_result = MagicMock()
    mock_result.authorized = True
    mock_mainlayer_client.resources.verify_access.return_value = mock_result

    result = await billing_client.verify_access("res_123", "token_abc")
    assert result is True
    mock_mainlayer_client.resources.verify_access.assert_awaited_once_with(
        "res_123", "token_abc"
    )


@pytest.mark.asyncio
async def test_verify_access_denied(billing_client, mock_mainlayer_client):
    mock_result = MagicMock()
    mock_result.authorized = False
    mock_mainlayer_client.resources.verify_access.return_value = mock_result

    result = await billing_client.verify_access("res_123", "bad-token")
    assert result is False


@pytest.mark.asyncio
async def test_verify_access_empty_inputs(billing_client):
    assert await billing_client.verify_access("", "token") is False
    assert await billing_client.verify_access("res", "") is False


@pytest.mark.asyncio
async def test_verify_access_exception_returns_false(billing_client, mock_mainlayer_client):
    mock_mainlayer_client.resources.verify_access.side_effect = Exception("Network timeout")
    result = await billing_client.verify_access("res_123", "token_abc")
    assert result is False


@pytest.mark.asyncio
async def test_deduct_minute_success(billing_client, mock_mainlayer_client):
    mock_result = MagicMock()
    mock_result.authorized = True
    mock_mainlayer_client.resources.verify_access.return_value = mock_result

    result = await billing_client.deduct_minute("res_voice", "token_abc")
    assert result is True


@pytest.mark.asyncio
async def test_deduct_minute_insufficient_credits(billing_client, mock_mainlayer_client):
    from mainlayer_billing import BillingError

    mock_result = MagicMock()
    mock_result.authorized = False
    mock_mainlayer_client.resources.verify_access.return_value = mock_result

    with pytest.raises(BillingError, match="Insufficient credits"):
        await billing_client.deduct_minute("res_voice", "broke-token")


@pytest.mark.asyncio
async def test_deduct_minute_empty_inputs(billing_client):
    from mainlayer_billing import BillingError

    with pytest.raises(BillingError):
        await billing_client.deduct_minute("", "token")

    with pytest.raises(BillingError):
        await billing_client.deduct_minute("res", "")


@pytest.mark.asyncio
async def test_deduct_minute_api_exception_raises_billing_error(
    billing_client, mock_mainlayer_client
):
    from mainlayer_billing import BillingError

    mock_mainlayer_client.resources.verify_access.side_effect = Exception("API down")
    with pytest.raises(BillingError, match="Mainlayer deduction failed"):
        await billing_client.deduct_minute("res_voice", "token")


@pytest.mark.asyncio
async def test_get_credit_balance_success(billing_client, mock_mainlayer_client):
    mock_status = MagicMock()
    mock_status.active = True
    mock_status.units_remaining = 120
    mock_status.plan = "pay-per-minute"
    mock_mainlayer_client.resources.get_status.return_value = mock_status

    result = await billing_client.get_credit_balance("res_voice", "token")
    assert result is not None
    assert result["active"] is True
    assert result["minutes_remaining"] == 120
    assert result["plan"] == "pay-per-minute"


@pytest.mark.asyncio
async def test_get_credit_balance_exception_returns_none(billing_client, mock_mainlayer_client):
    mock_mainlayer_client.resources.get_status.side_effect = Exception("API error")
    result = await billing_client.get_credit_balance("res_voice", "token")
    assert result is None


def test_billing_client_raises_without_api_key():
    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("MAINLAYER_API_KEY", None)
        from mainlayer_billing import BillingClient
        with pytest.raises(RuntimeError, match="MAINLAYER_API_KEY"):
            BillingClient()
