"""Skill: get current weather conditions for a location (via Open-Meteo, no API key needed)."""

from __future__ import annotations

import requests

SKILL_METADATA = {
    "name": "get_weather",
    "description": "Get the current weather conditions for a city or location.",
    "parameters": {
        "type": "object",
        "properties": {
            "location": {
                "type": "string",
                "description": "City name, e.g. 'Doha' or 'Tunis, Tunisia'.",
            }
        },
        "required": ["location"],
    },
}

_WEATHER_CODES = {
    0: "clear sky", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "depositing rime fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain",
    71: "light snow", 73: "snow", 75: "heavy snow",
    80: "light showers", 81: "showers", 82: "violent showers",
    95: "thunderstorm",
}


def run(location: str) -> dict:
    try:
        geo = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": location, "count": 1},
            timeout=10,
        )
        geo.raise_for_status()
        results = geo.json().get("results")
        if not results:
            return {"success": False, "message": f"Could not find a location matching '{location}'."}

        place = results[0]
        lat, lon = place["latitude"], place["longitude"]
        display_name = ", ".join(
            filter(None, [place.get("name"), place.get("admin1"), place.get("country")])
        )

        weather = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={"latitude": lat, "longitude": lon, "current_weather": "true"},
            timeout=10,
        )
        weather.raise_for_status()
        current = weather.json()["current_weather"]

        condition = _WEATHER_CODES.get(current["weathercode"], "unknown conditions")
        message = f"{display_name}: {condition}, {current['temperature']}°C, wind {current['windspeed']} km/h"
        return {"success": True, "message": message}

    except requests.RequestException as exc:
        return {"success": False, "message": f"Could not fetch weather for '{location}': {exc}"}