## Notification syntax

All notifications use the https://github.com/caronc/apprise syntax, there are some custom ones such as `posts` etc for general web-services usability.


## Template file notification wrappers

You can by default wrap all notifications by creating a `notification-wrapper-HTML-schema.html` in your datastore directory.

For example

You can use "`--`" in the filename where the _schema_ is to symbolize a wildcard. For example `notification-wrapper-HTML-mail--.html` would
apply to `mail://` `mailto://` etc etc

See is `notification-wrapper-HTML-mail--.html` which applies to `mail://`, `mailto://foobar..` etc notifications


