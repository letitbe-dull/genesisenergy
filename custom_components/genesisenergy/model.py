# custom_components/genesisenergy/model.py
from dataclasses import dataclass

from homeassistant.components.sensor import SensorEntityDescription
from homeassistant.components.binary_sensor import BinarySensorEntityDescription
from homeassistant.helpers.entity import EntityDescription

@dataclass(kw_only=True)
class GenesisEnergyEntityDescription(EntityDescription):
    """Base description for Genesis Energy entities."""

@dataclass(kw_only=True)
class GenesisEnergySensorEntityDescription(SensorEntityDescription, GenesisEnergyEntityDescription):
    """Describes Genesis Energy sensor entity."""

@dataclass(kw_only=True)
class GenesisEnergyBinarySensorEntityDescription(BinarySensorEntityDescription, GenesisEnergyEntityDescription):
    """Describes Genesis Energy binary sensor entity."""