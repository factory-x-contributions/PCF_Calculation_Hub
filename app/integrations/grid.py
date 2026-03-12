import requests
from datetime import datetime, timedelta, timezone

from app.integrations.oauth_token_cache import TokenCache


class GridInterface(object):
    def __init__(self):
        self.base_url = "https://explore.traxes.io/greengrid-compass/v1/co2-intensity"
        self.auth_url = "https://signin.energy/am/oauth2/realms/root/realms/difesp/access_token"
        self.client_id = "esp_AlirezaRanFactoryX3Ymc2H_001"
        self.client_sec = "9e2996TtBKga0NSbVXf9b6Be"
        self._token_cache = TokenCache(
            token_url=self.auth_url,
            client_id_provider=lambda: self.client_id,
            client_secret_provider=lambda: self.client_sec,
            extra_body={"scope": "esp"},
            body_format="form",
        )

    def get_token(self):
        token = self._token_cache.get()
        if token is None:
            raise RuntimeError(
                "Green Grid Compass credentials are required; "
                "GridInterface does not support unauthenticated mode."
            )
        return token

    def get_carbon_data(self, start, end, zone="DE_LU"):

        headers = {"Authorization": f"Bearer {self.get_token()}", "Accept": "application/json"}
        params = {
            "zone": zone,
            "start": start,
            "end": end,
            "time-resolution": "Hourly",
            "calculation-type": "Consumption",
            "emission-type": "Lifecycle"
            }
        
        response = requests.get(self.base_url, headers=headers, params=params)
        return response.json()
        
    def get_co2_coeff_list(self, start, end, zone="DE_LU"):
        data = self.get_carbon_data(start, end, zone)
        values = [
            mv["value"]
            for m in data.get("measurements", [])
            for mv in m.get("measurementValues", [])
            if mv.get("value") is not None
        ]
        return values
              
    def average_carbon_value(self, data):
        values = [
            mv["value"]
            for m in data.get("measurements", [])
            for mv in m.get("measurementValues", [])
            if mv.get("value") is not None
        ]
        if values:
            return float(sum(values) / len(values))
        return None
        
    def get_avg_carbon_coeff(self, start, end, zone="DE_LU") -> float:
        res = self.get_carbon_data(start, end, zone)
        return self.average_carbon_value(res)
        
def enforce_time_resolution(s, e, m, format="%Y-%m-%dT%H:%M:%SZ"):
    # Check if input is string and convert to datetime if needed
    if isinstance(s, str):
        s = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if isinstance(e, str):
        e = datetime.fromisoformat(e.replace("Z", "+00:00"))

    # Ensure that time difference is at least 'm' minutes
    if e - s < timedelta(minutes=m):
        e = s + timedelta(minutes=m)

    # Return as ISO 8601 string format
    return s.isoformat().replace("+00:00", "Z"), e.isoformat().replace("+00:00", "Z")

        
# gi = GridInterface()
# gi.get_carbon_data(start='2026-01-11T09:00:00Z', end='2026-01-11T12:00:00Z', zone="DE_LU",)










