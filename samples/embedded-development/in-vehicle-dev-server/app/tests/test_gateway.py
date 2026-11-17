"""How the app authenticates to the gateway: the gateway's own app token when the app has no secret file (Kiro Crew
keeps the secret out of the app's folder), else the install secret exchanged for a token."""

import asyncio

import pytest

from teamkit import mod

gateway = mod("gateway")


def test_without_a_secret_file_the_gateways_app_token_is_used(tmp_path):
    asked = []

    async def app_token():
        asked.append(1)
        return "tok-alice"

    async def go():
        gw = gateway.Gateway("vstatd-team", tmp_path / ".app_secret", app_token=app_token, clock=lambda: 0.0)
        assert await gw._token_now() == "tok-alice"
        assert await gw._token_now() == "tok-alice"  # kept until it is due for renewal
    asyncio.run(go())
    assert asked == [1]


def test_an_app_the_gateway_gives_no_token_says_so(tmp_path):
    async def app_token():
        return ""

    async def go():
        gw = gateway.Gateway("vstatd-team", tmp_path / ".app_secret", app_token=app_token, clock=lambda: 0.0)
        with pytest.raises(gateway.GatewayError, match="gave no app token"):
            await gw._token_now()
    asyncio.run(go())


def test_with_neither_the_missing_secret_file_is_the_error(tmp_path):
    async def go():
        gw = gateway.Gateway("vstatd-team", tmp_path / ".app_secret", clock=lambda: 0.0)
        with pytest.raises(FileNotFoundError):
            await gw._token_now()
    asyncio.run(go())
