import re
import requests
import base64
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.integrations.oauth_token_cache import TokenCache

_SIGREEN_TOKEN_URL = "https://siemens-00340.eu.auth0.com/oauth/token/"
_SIGREEN_AUDIENCE = "https://app-uat.sigreen-playground.siemens.cloud/"


def _resolve_credential(env_key: str, config_key: str) -> str:
    """Return the configured credential, preferring the runtime config over env vars.

    SiGREEN credentials are user-editable through the Config UI (which writes
    ``app_config.json`` via :func:`app.services.config_service.save_app_config`),
    so we read from there first. The env-var fallback is used by deploy
    scripts that prefer to inject creds at process start.
    """
    try:
        from app.services.config_service import load_app_config

        value = (load_app_config().get(config_key) or "").strip()
        if value:
            return value
    except Exception:
        pass
    return (os.environ.get(env_key, "") or "").strip()


def _sigreen_client_id() -> str:
    return _resolve_credential("SIGREEN_CLIENT_ID", "sigreen_client_id")


def _sigreen_client_secret() -> str:
    return _resolve_credential("SIGREEN_CLIENT_SECRET", "sigreen_client_secret")


# The provider lambdas resolve ``_sigreen_client_id`` / ``_sigreen_client_secret`` via the module
# object so ``unittest.mock.patch`` on those names reaches the cache; a direct closure would freeze
# the original function reference at import time and tests could not stub the credentials.
_SIGREEN_TOKEN_CACHE = TokenCache(
    token_url=_SIGREEN_TOKEN_URL,
    client_id_provider=lambda: sys.modules[__name__]._sigreen_client_id(),
    client_secret_provider=lambda: sys.modules[__name__]._sigreen_client_secret(),
    extra_body={"audience": _SIGREEN_AUDIENCE},
    body_format="json",
)


def clear_sigreen_token_cache() -> None:
    """Clear the token cache. Call when SiGREEN credentials change so the next API call uses fresh credentials."""
    _SIGREEN_TOKEN_CACHE.clear()


def _load_sigreen_product_identifier_type() -> str:
    """Load product identifier type from config. Must match the identifier type defined in SiGREEN for your company."""
    try:
        from app.services.config_service import load_app_config

        return (load_app_config().get("sigreen_product_identifier_type") or "Product ID").strip() or "Product ID"
    except Exception:
        return "Product ID"


def fetch_token() -> str | None:
    """Return a SiGREEN access token, or ``None`` when credentials are intentionally omitted.

    Spec FX TP2.10 §5.2.4 mandates an unauthenticated fallback for relaxed local
    SiGREEN deployments — callers must therefore handle ``None`` by omitting
    the Authorization header rather than treating it as an error.
    """
    return _SIGREEN_TOKEN_CACHE.get()


def _auth_headers() -> dict[str, str]:
    """Build SiGREEN request headers, omitting Authorization when no credentials are configured."""
    headers: dict[str, str] = {"Content-Type": "application/json"}
    token = fetch_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def base64_encode(data: str) -> str:
    """
    Encodes a string in base64 format.

    Args:
        data (str): The string to encode.

    Returns:
        str: The base64 encoded string.
    """
    return base64.b64encode(data.encode("utf-8")).decode("utf-8")


def save_dict_to_json(data: dict, filepath: Path) -> None:
    """
    Saves a dictionary to a JSON file.

    Args:
        data (dict): The dictionary to save.
        filepath (Path): The path to the JSON file.
    """
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)




DEFAULT_SIGREEN_BASE_URL = "https://app-uat.sigreen-playground.siemens.cloud/api"


class SiGREENInterface (object):
    def __init__(self, factory_name, factory_id=None, base_url=None):
        self.factory_id = factory_id
        self.factory_name = factory_name
        self.base_url = (base_url or "").strip() or DEFAULT_SIGREEN_BASE_URL
        if self.factory_id is None:
            self.factory_id = self.get_factory_id(self.factory_name)
        
    def send_factory_emissions(self, product_uuid, PCF_report):
        
        response = requests.post(
            f"{self.base_url}/products/{product_uuid}/factoryEmissions",
            headers=_auth_headers(),
            json=PCF_report,
            timeout=10)
        if not response.ok:
            try:
                err_body = response.json()
                err_msg = f"SiGREEN {response.status_code}: {err_body}"
            except Exception:
                err_msg = f"SiGREEN {response.status_code}: {response.text or '(empty body)'}"
            raise requests.HTTPError(err_msg, response=response)

    def get_factories(self):

        response = requests.get(
            f"{self.base_url}/factories",
            headers=_auth_headers(),
            timeout=10)
        response.raise_for_status() 
        return response.json()
        

    def get_factory_id(self, factory_name):
        """Look up factory ID by name. Case-insensitive, normalizes whitespace, matches 'factory' or 'name' field.

        Empty / whitespace-only ``factory_name`` short-circuits before the network call —
        an unconfigured factory name is a routine state during first-run setup, not an error.
        """
        name_clean = (factory_name or "").strip()
        if not name_clean:
            return None
        data = self.get_factories()
        name_normalized = re.sub(r"\s+", " ", name_clean).lower()
        for item in data.get("items", []):
            for key in ("factory", "name"):
                val = item.get(key)
                if isinstance(val, str):
                    val_normalized = re.sub(r"\s+", " ", val.strip()).lower()
                    if val_normalized == name_normalized:
                        return item.get("id")
        return None
        
    def get_products(self):

        response = requests.get(
            f"{self.base_url}/products",
            headers=_auth_headers(),
            timeout=10)
        response.raise_for_status() 
        return response.json()

    def get_product_uuid(self, product_id):
        # GET /products only supports idValue (not idType — unlike /components)
        response = requests.get(
            f"{self.base_url}/products",
            headers=_auth_headers(),
            params={"idValue": product_id},
            timeout=10)
        self.handle_response(response)
        data = response.json()
        items = data.get("items", [])
        if items:
            return items[0].get("id")
        # Fallback: fetch all products and match by identifier value or name
        try:
            response = requests.get(
                f"{self.base_url}/products",
                headers=_auth_headers(),
                timeout=10)
            self.handle_response(response)
            for item in response.json().get("items", []):
                for ident in item.get("identifiers", []):
                    if str(ident.get("value", "")).strip() == str(product_id).strip():
                        return item.get("id")
                if str(item.get("name", "")).strip() == str(product_id).strip():
                    return item.get("id")
        except Exception:
            pass
        return None

    # ---- SiGREEN Procurement API (components / material PCF) ----

    def get_components(self, id_value: str | None = None, id_type: str | None = None):
        """GET /components. Optional idValue and idType to filter by identifier."""
        params = {}
        if id_value:
            params["idValue"] = id_value
        if id_type:
            params["idType"] = id_type
        response = requests.get(
            f"{self.base_url}/components",
            headers=_auth_headers(),
            params=params if params else None,
            timeout=10,
        )
        self.handle_response(response)
        return response.json()

    def get_component_by_identifier(self, identifier: str, id_type: str | None = None):
        """Find component by identifier value. Returns component dict or None."""
        if id_type is None:
            id_type = _load_sigreen_product_identifier_type()
        # Try configured type first, then common alternates (MES often uses Material No.)
        id_types_to_try = [id_type, "Material No.", "Article Number", "Article number"]
        seen = set()
        for it in id_types_to_try:
            if not it or it in seen:
                continue
            seen.add(it)
            try:
                data = self.get_components(id_value=identifier, id_type=it)
            except Exception:
                continue
            items = data.get("items", [])
            if not items:
                continue
            for item in items:
                for ident in item.get("identifiers", []):
                    if str(ident.get("value", "")).strip() == str(identifier).strip():
                        return item
        # Fallback: fetch all and filter by identifier value (no id_type filter)
        try:
            data = self.get_components()
            items = data.get("items", [])
        except Exception:
            return None
        for item in items:
            for ident in item.get("identifiers", []):
                if str(ident.get("value", "")).strip() == str(identifier).strip():
                    return item
        return None

    def get_component_secondary_data(self, component_id: str):
        """GET /components/{id}/secondaryData - list secondary data for component."""
        response = requests.get(
            f"{self.base_url}/components/{component_id}/secondaryData",
            headers=_auth_headers(),
            timeout=10,
        )
        self.handle_response(response)
        return response.json()

    def get_component_pcf_data(self):
        """GET /components/pcfData - PCF data for components (supplier-shared)."""
        response = requests.get(
            f"{self.base_url}/components/pcfData",
            headers=_auth_headers(),
            timeout=10,
        )
        self.handle_response(response)
        return response.json()

    def _pcf_from_production_and_distribution(self, item: dict) -> float | None:
        """
        Extract total PCF (production + distribution stages) from a secondary data or pcfData item.
        Sums pcfIncludingBiogenic (or pcfExcludingBiogenic) from productionStage and distributionStage.
        Returns None only if neither stage has parseable PCF data.
        """
        prod = item.get("productionStage") or {}
        dist = item.get("distributionStage") or {}
        p_prod = prod.get("pcfIncludingBiogenic") or prod.get("pcfExcludingBiogenic") or 0
        p_dist = dist.get("pcfIncludingBiogenic") or dist.get("pcfExcludingBiogenic") or 0
        try:
            total = float(p_prod) + float(p_dist)
        except (TypeError, ValueError):
            return None
        return total

    def _pcf_stages_from_item(self, item: dict) -> tuple[float, float] | None:
        """
        Extract production and distribution stage PCF from a secondary data or pcfData item.

        Returns ``(production, distribution)`` in kg CO2e. Returns ``None`` when neither
        stage exists on the item (so callers can fall back to a top-level ``pcfIncludingBiogenic``
        field) or when the values are unparseable.
        """
        prod = item.get("productionStage")
        dist = item.get("distributionStage")
        if not prod and not dist:
            return None
        p_prod = (prod or {}).get("pcfIncludingBiogenic") or (prod or {}).get("pcfExcludingBiogenic") or 0
        p_dist = (dist or {}).get("pcfIncludingBiogenic") or (dist or {}).get("pcfExcludingBiogenic") or 0
        try:
            return (float(p_prod), float(p_dist))
        except (TypeError, ValueError):
            return None

    def get_material_pcf_per_unit_kg(
        self, identifier: str
    ) -> dict[str, float] | None:
        """
        Get carbon footprint per unit (kg CO2e) for a material/component from SiGREEN Procurement API.
        Includes both production stage and distribution stage PCF from component secondary data.
        Uses pcfIncludingBiogenic (or pcfExcludingBiogenic) from each stage.
        Returns None if component not found or no PCF data.
        """
        import logging
        log = logging.getLogger("pcf_creator_app")
        comp = self.get_component_by_identifier(identifier)
        if not comp:
            log.debug("SiGREEN: component not found for identifier=%r", identifier)
            return None
        comp_id = comp.get("id")
        if not comp_id:
            return None
        try:
            data = self.get_component_secondary_data(comp_id)
        except Exception as e:
            log.debug("SiGREEN: secondaryData failed for %r: %s", identifier, e)
            return None
        items = data.get("items", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        if not items:
            # Try pcfData endpoint as fallback
            try:
                pcf_data = self.get_component_pcf_data()
                pcf_items = pcf_data.get("items", [])
                for it in pcf_items:
                    if it.get("componentId") == comp_id or it.get("component", {}).get("id") == comp_id:
                        # Prefer production + distribution when stages are present
                        stages = self._pcf_stages_from_item(it)
                        if stages is not None:
                            p_prod, p_dist = stages
                            total = p_prod + p_dist
                            qty = it.get("quantity") or 1
                            try:
                                qty = float(qty)
                            except (TypeError, ValueError):
                                qty = 1.0
                            qty = qty or 1.0
                            return {
                                "total": total / qty,
                                "production": p_prod / qty,
                                "distribution": p_dist / qty,
                            }
                        # Fallback to top-level PCF value (no stage breakdown)
                        val = it.get("pcfIncludingBiogenic") or it.get("pcfValue") or it.get("totalPcf")
                        if val is not None:
                            v = float(val)
                            return {"total": v, "production": v, "distribution": 0.0}
            except Exception:
                pass
            return None
        # Use secondary data: ssaum production + distribution, return per-unit with stages.
        # Prefer the item with the highest total (most complete data, e.g. with distribution stage).
        best: dict[str, float] | None = None
        for sd in items:
            stages = self._pcf_stages_from_item(sd)
            if stages is None:
                continue
            p_prod, p_dist = stages
            total = p_prod + p_dist
            qty = sd.get("quantity") or 1
            try:
                qty = float(qty)
            except (TypeError, ValueError):
                qty = 1.0
            qty = qty or 1.0
            per_unit_total = total / qty
            per_unit_prod = p_prod / qty
            per_unit_dist = p_dist / qty
            if best is None or per_unit_total > (best.get("total") or 0):
                best = {
                    "total": per_unit_total,
                    "production": per_unit_prod,
                    "distribution": per_unit_dist,
                }
        return best

        
    def create_process_bill(self, total, pcf_share, type_of_activity, comment: str | None = None):
        bill = {
                  "typeOfActivity": type_of_activity,
                  "total": round(float(total), 6),
                  "primaryDataShare": 75.8,
                  "shareOnTotal": pcf_share,
                  "emissionUnit": "kgCO2e/piece",  # todo
                  "comment": comment or "Estimated values",
                  "fossil": 100.8,
                  "biogenic": 0,    # 300.5,
                  "dLuc": 0,        # 200.7,
                  "landUse": 0,     # 100.2,
                  "aircraft": 0     # 50.1
                }
        return bill

        
    def create_PCF_report(self, BOP, Total_PCF, quantity, t_start, t_end, batch_number=None):
        bop = {
              "revision": "1",
              "factoryId": self.factory_id,
              "factory": self.factory_name,
              "from":  t_start,    # "2024-01-01T00:00:00.000Z",
              "to":  t_end,        # "2024-01-02T23:59:59.590Z",
              "batch": {
                "batchNumber": batch_number or "Not provided",
                "quantity": quantity,  
                "assessmentYear": 2026,
                "dataSource": "PCF Creator APP V-1.0",
                "comment": "First batch of the year"
              },
               "productCarbonFootprint": round(float(Total_PCF), 6),
              "emissions": BOP,
              "comment": "Emission data from DMG Mori",
              "sourceSystem": "API"
            }
        return bop
        
    def create_product(self, name, prod_id, prod_family, id_type=None):
        if id_type is None:
            id_type = _load_sigreen_product_identifier_type()
        data = {
          "name": name,
          "family": prod_family,
          "identifiers": [
            {
              "value": prod_id,
              "idType": id_type,
              "default": True
            }
          ],
          "description": "Your product description", # todo 
          "weight": "1.533", # todo 
          "quantity": "1", # todo
          "unitType": "piece", # todo
          "factoryIds": [
            self.factory_id
          ]
        }

        response = requests.post(
            f"{self.base_url}/products",
            headers=_auth_headers(),
            json=data,
            timeout=10)
        self.handle_response(response)
        body = response.json()
        product_id_value = body.get("id")
        if product_id_value is None:
            raise ValueError(
                f"SiGREEN create_product response missing 'id': {body}"
            )
        return product_id_value


    def create_bom_version(self, uuid, comment=" "):

        bom_versions = self.get_prod_bom_versions(uuid)
        #latest = max( (tuple(map(int, item["version"].split("."))) for item in bom_versions["items"]), default=(0, 0, 0))
        #new_version = ".".join(map(str, (*latest[:-1], latest[-1] + 1)))
        new_version = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        data = {
              "version": new_version,
              "comment": comment,
              "revision": "1.9"
            }

        response = requests.post(
            f"{self.base_url}/products/{uuid}/bomVersions",
            headers=_auth_headers(),
            json=data,
            timeout=10)
        self.handle_response(response)
        return response.json()['id']

    def get_prod_bom_versions(self, uuid):

        response = requests.get(
            f"{self.base_url}/products/bomVersions",
            headers=_auth_headers(),
           params={
            "productId": uuid
            },  timeout=10)
        
        self.handle_response(response)
        return response.json()
        
    def get_product_bom(self, uuid, bom_id):
        response = requests.get(
            f"{self.base_url}/products/{uuid}/bom/{bom_id}",
            headers=_auth_headers(),
           params={
            "id": uuid,
            "bomVersionId": bom_id
            }, 
            timeout=10)
        
#        response.raise_for_status()
        self.handle_response(response)
        return response.json()
        
    def get_prod_last_bom_version(self, uuid):
        data = self.get_prod_bom_versions(uuid=uuid)
        last_version = data["items"][-1]["version"]
        last_version_id = data["items"][-1]["id"]
        return last_version, last_version_id
                               
    def handle_response(self, response):
        if not response.ok:
            try:
                detail = response.json()
            except ValueError:
                detail = response.text
            raise requests.HTTPError(
                f"{response.status_code} Error: {detail}",
                response=response,
            )
        return response.json()

