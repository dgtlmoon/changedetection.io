import pluggy
from typing import Dict
from changedetectionio.model import Watch as Watch

plugin_namespace = "changedetectionio.restock_price_scraper"
hookspec = pluggy.HookspecMarker(plugin_namespace)

class HookSpec:
    @hookspec
    def scrape_price_restock(self, watch: Watch.model, html_content: str, screenshot: bytes, update_obj: Dict) -> Dict:
        """
         Scrape price and restock data from html_content and/or screenshot and return via update_obj

         Args:
             watch (Watch.model): The watch object containing watch configuration.
             html_content (str): The HTML content to scrape.
             screenshot (bytes): The screenshot data.
             update_obj (Dict): The dictionary to update with scraped data.

         Returns:
             Optional[Dict]: The updated dictionary with the scraped price data, or None if no update is made.
         """

