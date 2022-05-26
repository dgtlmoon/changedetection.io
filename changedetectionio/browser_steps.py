#!/usr/bin/python3

from abc import abstractmethod

class BrowserStepBase():

    page = None # instance of

    # Blank step
    def choose_one(self, step):
        return

    @abstractmethod
    def enter_text_in_field(self, step):
        return

    @abstractmethod
    def wait_for_text(self, step):
        return

    @abstractmethod
    def wait_for_seconds(self, step):
        return

    @abstractmethod
    def click_button(self, step):
        return

    @abstractmethod
    def click_button_containing_text(self, step):
        return


# Good reference - https://playwright.dev/python/docs/input
#                  https://pythonmana.com/2021/12/202112162236307035.html
class browsersteps_playwright(BrowserStepBase):
    def enter_text_in_field(self, step):
        self.page.fill(step['selector'], step['optional_value'])
        return

    def wait_for_text(self, step):
        return

    def wait_for_seconds(self, step):
        self.page.wait_for_timeout(int(step['optional_value']) * 1000)
        return

    def click_button(self, step):
        self.page.click(step['selector'])
        return

    def click_button_containing_text(self, step):
        self.page.click("text="+step['optional_value'])
        return

    def select_by_label(self, step):
        self.page.select_option(step['selector'], label=step['optional_value'])
        return

class browsersteps_selenium(BrowserStepBase):
    def enter_text_in_field(self, step):
        return

    def wait_for_text(self, step):
        return

    def wait_for_seconds(self, step):
        return

    def click_button(self, step):
        return

    def click_button_containing_text(self, step):
        return