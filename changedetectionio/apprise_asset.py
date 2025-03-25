from apprise import AppriseAsset

# Refer to:
# https://github.com/caronc/apprise/wiki/Development_API#the-apprise-asset-object

APPRISE_APP_ID = "changedetection.io"
APPRISE_APP_DESC = "ChangeDetection.io best and simplest website monitoring and change detection"
APPRISE_APP_URL = "https://changedetection.io"
APPRISE_AVATAR_URL = "https://raw.githubusercontent.com/dgtlmoon/changedetection.io/master/changedetectionio/static/images/avatar-256x256.png"

apprise_asset = AppriseAsset(
    app_id=APPRISE_APP_ID,
    app_desc=APPRISE_APP_DESC,
    app_url=APPRISE_APP_URL,
    image_url_logo=APPRISE_AVATAR_URL,
)
