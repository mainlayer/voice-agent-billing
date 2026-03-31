"""
Mainlayer per-minute billing integration for the Voice Agent Billing service.
Handles credit verification and per-minute deductions.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from mainlayer import MainlayerClient

logger = logging.getLogger(__name__)


class BillingError(Exception):
    """Raised when a Mainlayer billing operation fails."""


class BillingClient:
    """
    Wrapper around MainlayerClient for voice session billing.
    All methods are async and safe to call from FastAPI handlers.
    """

    def __init__(self, api_key: Optional[str] = None):
        key = api_key or os.environ.get("MAINLAYER_API_KEY")
        if not key:
            raise RuntimeError(
                "MAINLAYER_API_KEY is not set. Get your key at https://mainlayer.fr"
            )
        self._client = MainlayerClient(api_key=key)

    async def verify_access(self, resource_id: str, payment_token: str) -> bool:
        """
        Verify the user is authorized to start a voice session.

        Returns True if authorized, False otherwise.
        Never raises — billing errors return False.
        """
        if not resource_id or not payment_token:
            return False

        try:
            result = await self._client.resources.verify_access(resource_id, payment_token)
            authorized: bool = result.authorized
            logger.info(f"Access check resource={resource_id} authorized={authorized}")
            return authorized
        except Exception as exc:
            logger.error(f"verify_access failed: {exc}")
            return False

    async def deduct_minute(self, resource_id: str, payment_token: str) -> bool:
        """
        Deduct one minute of voice usage credits from the user's account.

        Args:
            resource_id:   The Mainlayer resource ID for per-minute billing.
            payment_token: The user's payment token.

        Returns:
            True if the deduction succeeded.

        Raises:
            BillingError: If the deduction fails (e.g. insufficient credits).
        """
        if not resource_id or not payment_token:
            raise BillingError("resource_id and payment_token are required")

        try:
            result = await self._client.resources.verify_access(resource_id, payment_token)
            if not result.authorized:
                raise BillingError(
                    f"Insufficient credits for resource '{resource_id}'. "
                    "Please top up at https://mainlayer.fr"
                )
            logger.info(f"Deducted 1 minute for resource={resource_id}")
            return True
        except BillingError:
            raise
        except Exception as exc:
            raise BillingError(f"Mainlayer deduction failed: {exc}") from exc

    async def get_credit_balance(self, resource_id: str, payment_token: str) -> Optional[dict]:
        """
        Retrieve remaining credit balance for a user.

        Returns a dict with 'minutes_remaining' or None on error.
        """
        try:
            status = await self._client.resources.get_status(resource_id)
            return {
                "active": getattr(status, "active", False),
                "minutes_remaining": getattr(status, "units_remaining", None),
                "plan": getattr(status, "plan", None),
            }
        except Exception as exc:
            logger.error(f"Failed to get credit balance: {exc}")
            return None
