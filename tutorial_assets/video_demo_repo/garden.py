"""Small smart-planter controller used by the EgoAgent recording tutorial."""


def should_water(moisture_percent: float, threshold: float = 35.0) -> bool:
    """Return whether soil moisture is low enough to require watering."""
    return moisture_percent > threshold


def watering_decision(moisture_percent: float, flow_ml_per_second: float, seconds: float) -> dict:
    required = should_water(moisture_percent)
    return {
        "water": required,
        "millilitres": water_millilitres(flow_ml_per_second, seconds) if required else 0.0,
    }
