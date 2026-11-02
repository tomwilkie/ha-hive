"""Support for the Hive devices and services."""

from collections.abc import Iterator
from typing import cast, override

from hiveheating import Device, Mode, Nodes, Product

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HiveDataUpdateCoordinator

# The modes a product can be set to.
MODES = ("SCHEDULE", "MANUAL", "OFF")


def current_mode(product: Product) -> str | None:
    """Return the product's mode: SCHEDULE, MANUAL or OFF, or None if unknown.

    While a boost is active Hive reports BOOST, so the mode the boost will
    return to is reported instead. Hive reports a previous mode of "off" as
    False.
    """
    mode = product.previous_mode if product.mode == "BOOST" else product.mode
    if mode is False:
        return "OFF"
    return mode if isinstance(mode, str) else None


def boost_minutes(time_period: float) -> int:
    """Return a boost's length in whole minutes.

    Raises:
        ServiceValidationError: The boost is shorter than a minute.
    """
    minutes = int(time_period)
    if minutes <= 0:
        raise ServiceValidationError(
            f"Boost minutes must be positive, not {time_period}"
        )
    return minutes


def display_name(name: str | None) -> str | None:
    """Return the name to show; Hive calls a heating-only thermostat "Receiver"."""
    return "Heating" if name == "Receiver" else name


def find_hub(nodes: Nodes) -> Device | None:
    """Return the hub, or None when Hive did not report one."""
    return next(
        (device for device in nodes.devices.values() if device.type == "hub"), None
    )


def attached_device(nodes: Nodes, product: Product) -> Device | None:
    """Return the hardware that carries a product, or None if it is its own device.

    Heating and hot water belong to the thermostat in their zone.
    """
    if not product.zone:
        return None
    return next(
        (
            device
            for device in nodes.devices.values()
            if device.type == "thermostatui" and device.zone == product.zone
        ),
        None,
    )


def discover(
    nodes: Nodes, types: tuple[str, ...]
) -> Iterator[tuple[Product, Device | None]]:
    """Yield each product of the given types with the hardware that carries it."""
    for product in nodes.products.values():
        if product.type in types:
            yield product, attached_device(nodes, product)


class HiveEntity(CoordinatorEntity[HiveDataUpdateCoordinator]):
    """Initiate Hive Base Class.

    Entities are named by Home Assistant from the device registry: the
    friendly name is the device's name followed by the entity's own, so a
    device the user renamed carries its new name into every entity.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HiveDataUpdateCoordinator,
        product: Product,
        device: Device | None,
    ) -> None:
        """Initialize the instance."""
        super().__init__(coordinator)
        self.hive = coordinator.hive
        self._product_id = product.id
        self._device_id = device.id if device else None
        self._attr_unique_id = f"{product.id}-{product.type}"
        # A product with no hardware of its own is its own device, and has
        # no manufacturer.
        if device is None:
            device_id = product.id
            device_info = DeviceInfo(
                identifiers={(DOMAIN, product.id)},
                model=product.model,
                name=display_name(product.name),
                sw_version=product.version,
            )
        else:
            device_id = device.id
            device_info = DeviceInfo(
                identifiers={(DOMAIN, device.id)},
                model=device.model,
                manufacturer=device.manufacturer,
                name=display_name(device.name),
                sw_version=device.version,
            )
        hub = find_hub(coordinator.data)
        if hub is not None and hub.id != device_id:
            device_info["via_device_id"] = dr.async_get_device_id_by_identifier(
                coordinator.hass,
                (DOMAIN, hub.id),
                config_entry_id=coordinator.config_entry.entry_id,
            )
        self._attr_device_info = device_info

    @property
    def product(self) -> Product | None:
        """Return the product from the latest snapshot."""
        return self.coordinator.data.products.get(self._product_id)

    @property
    def device(self) -> Device | None:
        """Return the hardware that carries the product, from the latest snapshot.

        None when the product is its own device.
        """
        return self.coordinator.data.devices.get(self._device_id or "")

    @property
    @override
    def available(self) -> bool:
        """Return whether the product is online.

        A failed refresh keeps the last snapshot, and with it the last state.
        """
        product = self.product
        return product is not None and bool(product.online)

    async def async_end_boost(self) -> None:
        """End an active boost by restoring the mode it will return to.

        Does nothing when the product is not boosting.

        Raises:
            HomeAssistantError: Hive did not report the mode to restore.
        """
        product = self.product
        if product is None or not product.boost:
            return
        mode = product.previous_mode
        if mode is False:
            mode = "OFF"
        if mode not in MODES:
            raise HomeAssistantError(
                f"Hive did not report the mode to restore for {product.name}"
            )
        # TODO: the old library also restored the previous target (or 7)
        # when returning to MANUAL or OFF; that waits for set_mode to take a
        # target in hiveheating.
        await self.hive.set_mode(product, cast(Mode, mode))
