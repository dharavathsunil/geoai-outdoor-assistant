import requests
from datetime import datetime

HEADERS = {"User-Agent": "geoai-hackathon-sunil/0.1 (student project)"}


def geocode(place: str):
    """Place name -> (lat, lon, display_name) using Nominatim."""
    r = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": place, "format": "json", "limit": 1, "countrycodes": "in"},
        headers=HEADERS,
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    if not data:
        return None
    return float(data[0]["lat"]), float(data[0]["lon"]), data[0]["display_name"]


def get_weather(lat: float, lon: float, days: int = 3):
    """Hourly forecast from Open-Meteo."""
    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "hourly": "temperature_2m,apparent_temperature,relative_humidity_2m,"
                      "precipitation_probability,precipitation,wind_speed_10m,"
                      "wind_direction_10m,cloud_cover,uv_index",
            "daily": "sunrise,sunset",
            "timezone": "Asia/Kolkata",
            "forecast_days": days,
        },
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def get_air_quality(lat: float, lon: float, days: int = 3):
    """Hourly air quality from Open-Meteo."""
    r = requests.get(
        "https://air-quality-api.open-meteo.com/v1/air-quality",
        params={
            "latitude": lat,
            "longitude": lon,
            "hourly": "pm2_5,pm10,us_aqi,ozone,nitrogen_dioxide",
            "timezone": "Asia/Kolkata",
            "forecast_days": days,
        },
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


if __name__ == "__main__":
    place = "Koregaon Park, Pune"
    geo = geocode(place)
    if not geo:
        raise SystemExit("Place not found")
    lat, lon, name = geo
    print(f"Place: {name}\nCoordinates: {lat:.4f}, {lon:.4f}\n")

    w = get_weather(lat, lon)
    aq = get_air_quality(lat, lon)

    print("Sunrise/Sunset today:", w["daily"]["sunrise"][0], "/", w["daily"]["sunset"][0], "\n")
    print(f"{'Time':<17}{'Temp':>6}{'Feels':>7}{'Rain%':>7}{'Wind':>6}{'Dir':>5}{'UV':>5}{'AQI':>6}{'PM2.5':>7}")
    now = datetime.now().strftime("%Y-%m-%dT%H:00")
    times = w["hourly"]["time"]
    start = times.index(now) if now in times else 0
    for i in range(start, start + 24):
        h, a = w["hourly"], aq["hourly"]
        print(
            f"{times[i]:<17}"
            f"{h['temperature_2m'][i]:>6}{h['apparent_temperature'][i]:>7}"
            f"{h['precipitation_probability'][i]:>7}{h['wind_speed_10m'][i]:>6}"
            f"{h['wind_direction_10m'][i]:>5}{h['uv_index'][i]:>5}"
            f"{str(a['us_aqi'][i]):>6}{str(a['pm2_5'][i]):>7}"
        )