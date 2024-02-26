from playwright.sync_api import PlaywrightContextManager

# So playwright wants to run as a context manager, but we do something horrible and hacky
# we are holding the session open for as long as possible, then shutting it down, and opening a new one
# So it means we don't get to use PlaywrightContextManager' __enter__ __exit__
# To work around this, make goodbye() act the same as the __exit__()
#
# But actually I think this is because the context is opened correctly with __enter__() but we timeout the connection
# then theres some lock condition where we cant destroy it without it hanging

class c_PlaywrightContextManager(PlaywrightContextManager):

    def goodbye(self) -> None:
        self.__exit__()

def c_sync_playwright() -> PlaywrightContextManager:
    return c_PlaywrightContextManager()
