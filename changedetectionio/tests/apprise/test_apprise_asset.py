import pytest
from apprise import AppriseAsset

from changedetectionio.apprise_asset import (
    APPRISE_APP_DESC,
    APPRISE_APP_ID,
    APPRISE_APP_URL,
    APPRISE_AVATAR_URL,
)


@pytest.fixture(scope="function")
def apprise_asset() -> AppriseAsset:
    from changedetectionio.apprise_asset import apprise_asset

    return apprise_asset


def test_apprise_asset_init(apprise_asset: AppriseAsset):
    assert isinstance(apprise_asset, AppriseAsset)
    assert apprise_asset.app_id == APPRISE_APP_ID
    assert apprise_asset.app_desc == APPRISE_APP_DESC
    assert apprise_asset.app_url == APPRISE_APP_URL
    assert apprise_asset.image_url_logo == APPRISE_AVATAR_URL
