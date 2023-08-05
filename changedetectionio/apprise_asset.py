import apprise

# Create our AppriseAsset and populate it with some of our new values:
# https://github.com/caronc/apprise/wiki/Development_API#the-apprise-asset-object
asset = apprise.AppriseAsset(
   image_url_logo='https://raw.githubusercontent.com/dgtlmoon/changedetection.io/master/changedetectionio/static/images/avatar-256x256.png'
)

asset.app_id = "changedetection.io"
asset.app_desc = "ChangeDetection.io best and simplest website monitoring and change detection"
asset.app_url = "https://changedetection.io"
