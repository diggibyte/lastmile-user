import os
import requests

MAPBOX_TOKEN = os.getenv("MAPBOX_TOKEN")

def get_traffic_update(
    start_lat, start_lon,
    end_lat, end_lon
):
    url = (
        f"https://api.mapbox.com/directions/v5/mapbox/driving-traffic/"
        f"{start_lon},{start_lat};{end_lon},{end_lat}"
    )

    params = {
        "geometries": "geojson",
        "overview": "full",
        "annotations": "duration",
        "access_token": MAPBOX_TOKEN
    }

    response = requests.get(url, params=params)
    response.raise_for_status()
    data = response.json()

    route = data["routes"][0]

    duration_with_traffic = route["duration"]               # seconds
    duration_typical = route["duration_typical"]             # seconds
    traffic_delay = duration_with_traffic - duration_typical

    return {
        "duration_with_traffic_min": round(duration_with_traffic / 60, 1),
        "duration_typical_min": round(duration_typical / 60, 1),
        "traffic_delay_min": round(traffic_delay / 60, 1),
        "geometry": route["geometry"]
    }


if __name__ == "__main__":
    traffic = get_traffic_update(
        start_lat=34.0522, start_lon=-118.2437,
        end_lat=40.7128, end_lon=-74.0060
    )

    print(traffic["traffic_delay_min"])
