"""The Hive data update coordinator."""

from dataclasses import replace
from datetime import timedelta
import logging

from apyhiveapi import (
    Hive,
    HiveConnectionError,
    HiveError,
    HiveReauthRequired,
    Nodes,
    Product,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

type HiveConfigEntry = ConfigEntry[HiveDataUpdateCoordinator]

SCAN_INTERVAL = timedelta(seconds=120)

# How many polls in a row a degraded product is replaced by its last good
# snapshot before the reply is shown as Hive sent it, so a real outage shows.
MAX_DEGRADED_POLLS = 5


def _is_degraded(product: Product) -> bool:
    """Return whether Hive sent the product's state without its mode.

    Every so often Hive answers with a product whose state holds only its
    name (apyhiveapi issue #20); the reply also misreports it as offline.
    """
    return product.mode is None


class HiveDataUpdateCoordinator(DataUpdateCoordinator[Nodes]):
    """Fetch every Hive product and device with one GET /nodes/all."""

    config_entry: HiveConfigEntry

    def __init__(self, hass: HomeAssistant, entry: HiveConfigEntry, hive: Hive) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
            # Nodes are frozen dataclasses that compare by value.
            always_update=False,
        )
        self.hive = hive
        self._degraded_polls: dict[str, int] = {}

    async def _async_update_data(self) -> Nodes:
        """Fetch the latest snapshot from Hive."""
        try:
            nodes = await self.hive.get_nodes()
        except HiveReauthRequired as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except HiveConnectionError as err:
            raise UpdateFailed(str(err)) from err
        except HiveError as err:
            # Hive refusing the first request is a setup error; after that it
            # is one failed poll.
            if self.data is None:
                raise ConfigEntryError(str(err)) from err
            raise UpdateFailed(str(err)) from err
        return self._keep_degraded_products(nodes)

    def _keep_degraded_products(self, nodes: Nodes) -> Nodes:
        """Replace each degraded product with its last good snapshot, up to the cap."""
        if self.data is None:
            return nodes
        products = dict(nodes.products)
        for product_id, product in nodes.products.items():
            previous = self.data.products.get(product_id)
            if previous is None or not _is_degraded(product):
                self._degraded_polls.pop(product_id, None)
                continue
            polls = self._degraded_polls.get(product_id, 0) + 1
            self._degraded_polls[product_id] = polls
            if polls > MAX_DEGRADED_POLLS:
                continue
            _LOGGER.debug(
                "Hive sent %s %s without its state, keeping the last known one",
                product.type,
                product_id,
            )
            products[product_id] = previous
        return replace(nodes, products=products)
