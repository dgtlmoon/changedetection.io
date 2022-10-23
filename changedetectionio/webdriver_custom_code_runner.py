import argparse
import shlex
from enum import Enum


class WebdriverMode(Enum):
    PLAYWRIGHT = 1
    SELENIUM = 2


class WebdriverCustomCodeRunner:
    def __init__(self, webdriver_object, webdriver_mode: WebdriverMode):
        self._webdriver_object = webdriver_object
        self._webdriver_mode = webdriver_mode
        self._parser = None

    def run(self, code: str):
        if not (code and code.strip()):
            return

        webdriver_command = code.strip()
        runner = None

        if self._webdriver_mode == WebdriverMode.PLAYWRIGHT:
            self._parser = WebdriverCustomCodeRunner._get_parser_playwright()
            runner = lambda command: self._run_playwright(command)
        elif self._webdriver_mode == WebdriverMode.SELENIUM:
            self._parser = WebdriverCustomCodeRunner._get_parser_selenium()
            runner = lambda command: self._run_selenium(command)

        for webdriver_command in webdriver_command.split('\n'):
            webdriver_command = webdriver_command.strip()
            if not webdriver_command:
                continue

            runner(webdriver_command)

    @staticmethod
    def _get_parser_selenium():
        parser = argparse.ArgumentParser()
        parser.add_argument('--action', type=str, nargs=1, choices=['click', 'send_keys'], required=True)
        parser.add_argument('--selector', type=str, nargs=1, required=True)
        parser.add_argument('--selector_type', type=str, nargs=1,
                            choices=['id', 'name', 'xpath', 'link_text', 'partial_link_text', 'tag_name', 'class_name',
                                     'css_selector'], required=True)
        parser.add_argument('--send_keys_value', type=str, nargs=1)
        return parser

    @staticmethod
    def _get_parser_playwright():
        parser = argparse.ArgumentParser()
        parser.add_argument('--action', type=str, nargs=1, choices=['click', 'fill', 'press'], required=True)
        parser.add_argument('--selector', type=str, nargs=1, required=True)
        parser.add_argument('--first', action='store_true', default=False)
        parser.add_argument('--fill_value', type=str, nargs=1)
        parser.add_argument('--press_value', type=str, nargs=1)
        return parser

    def _run_selenium(self, command: str):
        from selenium.webdriver import Keys

        args = self._parser.parse_args(shlex.split(command))

        if args.action[0] == 'click':
            self._selenium_find_element_by_selector_type(args.selector_type[0], args.selector[0]).click()
        elif args.action[0] == 'send_keys':
            send_keys_value_mapped = args.send_keys_value[0]
            selenium_keys_dict = {key: value for key, value in Keys.__dict__.items() if
                                  not key.startswith('__') and not callable(key)}
            if send_keys_value_mapped and send_keys_value_mapped in selenium_keys_dict.keys():
                send_keys_value_mapped = selenium_keys_dict[send_keys_value_mapped]

            if not args.send_keys_value:
                raise argparse.ArgumentError('missing "--send_keys_value" argument')
            else:
                self._selenium_find_element_by_selector_type(args.selector_type[0], args.selector[0]).send_keys(
                    send_keys_value_mapped)
        else:
            raise argparse.ArgumentError(f'action "{args.action[0]}" is not supported!')

    def _selenium_find_element_by_selector_type(self, selector_type: str, value: str):
        from selenium.webdriver.common.by import By

        if selector_type == 'id':
            return self._webdriver_object.find_element(by=By.ID, value=value)
        elif selector_type == 'name':
            return self._webdriver_object.find_element(by=By.NAME, value=value)
        elif selector_type == 'xpath':
            return self._webdriver_object.find_element(by=By.XPATH, value=value)
        elif selector_type == 'link_text':
            return self._webdriver_object.find_element(by=By.LINK_TEXT, value=value)
        elif selector_type == 'partial_link_text':
            return self._webdriver_object.find_element(by=By.PARTIAL_LINK_TEXT, value=value)
        elif selector_type == 'tag_name':
            return self._webdriver_object.find_element(by=By.TAG_NAME, value=value)
        elif selector_type == 'class_name':
            return self._webdriver_object.find_element(by=By.CLASS_NAME, value=value)
        elif selector_type == 'css_selector':
            return self._webdriver_object.find_element(by=By.CSS_SELECTOR, value=value)
        else:
            raise argparse.ArgumentError(f'selector_type "{selector_type}" is not supported!')

    def _run_playwright(self, command: str):
        args = self._parser.parse_args(shlex.split(command))

        def auto_locator(selector: str, first: bool):
            if first:
                return self._webdriver_object.locator(selector).first
            else:
                return self._webdriver_object.locator(selector)

        if args.action[0] == 'click':
            auto_locator(args.selector[0], args.first).click()
        elif args.action[0] == 'fill':
            if not args.fill_value:
                raise argparse.ArgumentError('missing "--fill_value" argument')
            else:
                auto_locator(args.selector[0], args.first).fill(args.fill_value[0])
        elif args.action[0] == 'press':
            if not args.press_value:
                raise argparse.ArgumentError('missing "--press_value" argument')
            else:
                auto_locator(args.selector[0], args.first).press(args.press_value[0])
        else:
            raise argparse.ArgumentError(f'action "{args.action[0]}" is not supported!')
