import logging
import aiohttp
from datetime import datetime

logger_currency = logging.getLogger('log.currency_conversion')


class CurrencyConverter:
    """Class to handle currency conversion operations"""

    def __init__(self):
        self.exchange_rates = {}
        self.last_updated = None

    async def update_exchange_rates(self):
        """Fetch current exchange rates from PrivatBank API"""
        try:
            async with aiohttp.ClientSession() as session:
                url = "https://api.privatbank.ua/p24api/pubinfo?json&exchange&coursid=5"
                async with session.get(url, timeout=10) as response:
                    if response.status != 200:
                        logger_currency.warning(f'Failed to get exchange rates: Status {response.status}')
                        return False

                    data = await response.json()

                    # Reset rates dictionary
                    self.exchange_rates = {}

                    # Parse the response
                    for rate in data:
                        if rate.get('base_ccy') == 'UAH':
                            ccy = rate.get('ccy')
                            # Using 'buy' rate as specified
                            buy_rate = float(rate.get('buy', 0))
                            if buy_rate > 0:
                                self.exchange_rates[ccy] = buy_rate

            self.last_updated = datetime.now()
            logger_currency.info(f'Exchange rates updated: {self.exchange_rates}')
            return True

        except Exception as ex:
            logger_currency.error(f'Error updating exchange rates: {ex}')
            return False

    async def convert_to_uah(self, amount, currency):
        """Convert amount from given currency to UAH"""
        if not amount:
            return 0

        # If already in UAH, return as is
        if currency == 'UAH':
            return float(amount)

        if not self.exchange_rates:
            await self.update_exchange_rates()

        # If we have an exchange rate for this currency
        if currency in self.exchange_rates:
            return float(amount) * self.exchange_rates[currency]

        # Default fallback - log warning and return original amount
        logger_currency.warning(f'No exchange rate found for {currency}, returning unconverted amount')
        return float(amount)


# Create a global instance
currency_converter = CurrencyConverter()
