import base64
import time

import requests


def base64url_encode(data: str) -> str:
    """Base64url-encode a string (no padding), as required by BaSyx AAS V3 API."""
    return base64.urlsafe_b64encode(data.encode("utf-8")).decode("utf-8").rstrip("=")


# New AAS_WO model uses ProcessOperationStatus (DMG) or OperationStatus (Trumpf) in MachineDetails.
PROPERTY_ALIASES = {"OperationStatus": ["OperationStatus", "ProcessOperationStatus"]}

# EnergyConsumption "Name" property variants seen in AAS payloads (AssetFox occasionally uses
# "Compressed Air" with a space, etc.). Map any variant onto the canonical key used internally.
ENERGY_NAME_ALIASES = {
    "CompressedAir": ["CompressedAir", "Compressed Air", "compressedair", "compressed air"],
    "electricity": ["electricity", "Electricity", "ELECTRICITY"],
}


def _normalize_energy_name(name: str) -> str:
    """Map an AAS Name value (any spelling) to the canonical key used in energy_updates."""
    if not name:
        return name
    name_stripped = str(name).strip()
    for canonical, aliases in ENERGY_NAME_ALIASES.items():
        if name_stripped in aliases:
            return canonical
    return name_stripped


class AASInterface(object):
    def __init__(self, asset_name='f-x-template-ohne-mes-001',
                       submodel_name='Factory-X ManufacturingProcess-001',
                       base_url=None,
                       client_id=None,
                       client_secret=None,
                       aas_type='AAS (BaSyx)',
                ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.asset_name = asset_name
        self.submodel_name = submodel_name
        self.asset_id = base64url_encode(self.asset_name)
        self.submodel_id = base64url_encode(self.submodel_name)
        self.aas_type = aas_type
        self.active_process = None
        self.bop_submodel_id = None
        self.bop_shell_id = None

        if base_url is None:
            if self.aas_type == 'AAS (BaSyx)':
                base_url = "http://localhost:8081"
            else:
                base_url = "https://test.assetfox.apps.siemens.cloud/api/aas/v3"

        base_url = base_url.rstrip("/")
        self.registry_base_url = base_url  # Used for discover_bop_machines and BOP submodel operations
        if self.aas_type == 'AAS (BaSyx)':
            self.base_url = base_url
        else:
            self.aas_type = 'AAS (AssetFox)'
            self.base_url = f"{base_url}/shells/{self.asset_id}"

        # Auto-discover submodel when: submodel_name==asset_name, or submodel looks wrong (e.g. /asset/ in path)
        if base_url and (
            submodel_name == asset_name
            or "/ids/asset/" in str(submodel_name)
        ):
            self._resolve_submodel_with_machine_details()

    def _resolve_submodel_with_machine_details(self):
        """When submodel_name==asset_name or invalid, find the submodel that contains MachineDetails."""
        try:
            refs = self.get_submodel_refs(self.asset_name)
            for sm_ref in refs:
                sm_id = base64url_encode(sm_ref)
                resp = requests.get(
                    f"{self.registry_base_url}/submodels/{sm_id}",
                    headers=self._headers(), timeout=10,
                )
                if resp.status_code != 200 or not resp.content or not resp.text.strip():
                    continue
                try:
                    sm = resp.json()
                except ValueError:
                    continue
                elems = sm.get("submodelElements", sm.get("value", []))
                if not isinstance(elems, list):
                    continue
                for e in elems:
                    if e.get("idShort") == "MachineDetails":
                        self.submodel_name = sm_ref
                        self.submodel_id = sm_id
                        return
                    for c in (e.get("value") or []):
                        if isinstance(c, dict) and c.get("idShort") == "MachineDetails":
                            self.submodel_name = sm_ref
                            self.submodel_id = sm_id
                            return
            # Fallback: use submodel index 1 (typically Bill_of_Process / ManufacturingProcess)
            if len(refs) >= 2:
                self.submodel_name = refs[1]
                self.submodel_id = base64url_encode(refs[1])
        except Exception:
            pass  # Keep original submodel_name; will fail on first API call

    def _headers(self) -> dict:
        """Build request headers, including auth only for AssetFox."""
        headers = {"Content-Type": "application/json"}
        if self.aas_type == 'AAS (AssetFox)':
            headers["Authorization"] = f"Bearer {self.fetch_assetfox_token()}"
        return headers

    def _submodel_url(self, sm_id: str, shell_id: str | None = None, *, element_path: str = "") -> str:
        """Return the canonical submodel (or submodel-element) URL for this AAS variant.

        BaSyx exposes submodels under ``/submodels/{sm_id}``; AssetFox requires the
        shell-scoped path ``/shells/{shell_enc}/submodels/{sm_id}`` and only falls
        back to the registry path on a 404. ``sm_id`` must already be base64url-encoded.
        """
        suffix = f"/submodel-elements/{element_path}" if element_path else ""
        if self.aas_type == 'AAS (BaSyx)' or shell_id is None:
            return f"{self.registry_base_url}/submodels/{sm_id}{suffix}"
        shell_enc = base64url_encode(shell_id)
        return f"{self.registry_base_url}/shells/{shell_enc}/submodels/{sm_id}{suffix}"

    def fetch_assetfox_token(self) -> str | None:
        """Return an AssetFox access token, or ``None`` for the BaSyx (no-auth) variant.

        Wraps a :class:`app.integrations.oauth_token_cache.TokenCache` configured
        with form-urlencoded body — same shape as the AssetFox IdP expects — so
        the cache logic is identical to SiGREEN's and Grid Compass's.
        """
        if self.aas_type == 'AAS (BaSyx)':
            return None
        cache = getattr(self, "_assetfox_token_cache_obj", None)
        if cache is None:
            from app.integrations.oauth_token_cache import TokenCache

            cache = TokenCache(
                token_url="https://test.assetfox.apps.siemens.cloud/auth/realms/assetfox/protocol/openid-connect/token",
                client_id_provider=lambda: self.client_id or "***REMOVED***",
                client_secret_provider=lambda: self.client_secret or "***REMOVED***",
                body_format="form",
            )
            self._assetfox_token_cache_obj = cache
        return cache.get()

    def find_shells(self):
        if self.aas_type == 'AAS (BaSyx)':
            url = f"{self.registry_base_url}/shells"
        else:
            url = f"{self.registry_base_url}/lookup/shells"
        response = requests.get(url, headers=self._headers(), timeout=10)
        response.raise_for_status()
        return response.json()

    def get_shell_asset(self, shell_name):
        self.asset_id = base64url_encode(shell_name)
        # Shells are at registry level; AssetFox base_url is shell-specific, so use registry_base_url
        url = f"{self.registry_base_url}/shells/{self.asset_id}"
        response = requests.get(url, headers=self._headers(), timeout=10)
        response.raise_for_status()
        return response.json()

    def get_submodel_refs(self, shell_id=None):
        """Get submodel reference values for a shell. Use these as submodel_name for get_property etc.

        Returns list of submodel identifiers (URNs) from the shell descriptor.
        Example: shell_id='f-x-template-ohne-mes-001' or the shell's full id.
        """
        sid = shell_id or self.asset_name
        shell = self.get_shell_asset(sid)
        refs = []
        for sm in shell.get("submodels", []):
            try:
                val = sm["keys"][0]["value"]
                refs.append(val)
            except (KeyError, IndexError):
                continue
        return refs

    @classmethod
    def for_asset(cls, asset_name, base_url, aas_type="AAS (BaSyx)", client_id=None, client_secret=None,
                  submodel_index=0):
        """Create an interface for an asset, auto-discovering the submodel from the shell.

        Use when submodel identifier is unknown. Fetches the shell and uses submodel at index.

        Args:
            submodel_index: 0=first submodel (often CommonParameter), 1=second (often Bill_of_Process
                with MachineDetails). Use get_submodel_top_level_elements() to inspect structure.

        Example:
            bsx = AASInterface.for_asset('f-x-template-ohne-mes-001',
                     base_url='http://10.19.1.136:8081', aas_type='AAS (BaSyx)', submodel_index=1)
            bsx.get_property(element_id='MachineDetails', idShort='OperationStatus')
        """
        inst = cls(asset_name=asset_name, submodel_name="placeholder", base_url=base_url,
                   client_id=client_id, client_secret=client_secret, aas_type=aas_type)
        refs = inst.get_submodel_refs(asset_name)
        if not refs:
            raise ValueError(f"No submodels found for asset {asset_name}")
        inst.submodel_name = refs[submodel_index]
        inst.submodel_id = base64url_encode(inst.submodel_name)
        return inst

    def get_asset_submodel(self):
        url = f"{self.base_url}/submodels/{self.submodel_id}"
        response = requests.get(url, headers=self._headers(), timeout=10)
        if response.status_code == 404 and self.aas_type == "AAS (AssetFox)":
            url = f"{self.registry_base_url}/submodels/{self.submodel_id}"
            response = requests.get(url, headers=self._headers(), timeout=10)
        response.raise_for_status()
        return response.json()

    def get_submodel_top_level_elements(self):
        """Return idShort of top-level elements. Use to find correct element_id for get_property."""
        sm = self.get_asset_submodel()
        elems = sm.get("submodelElements", sm.get("value", []))
        return [e.get("idShort") for e in elems if e.get("idShort")]

    def get_asset_submodel_element(self, element_id):
        url = f"{self.base_url}/submodels/{self.submodel_id}/submodel-elements/{element_id}"
        response = requests.get(url, headers=self._headers(), timeout=10)
        if self.aas_type == "AAS (AssetFox)" and (response.status_code == 404 or not response.content):
            url = f"{self.registry_base_url}/submodels/{self.submodel_id}/submodel-elements/{element_id}"
            response = requests.get(url, headers=self._headers(), timeout=10)
        response.raise_for_status()
        if not response.content:
            raise ValueError(f"Empty response from {url}")
        return response.json()

    def _find_item_by_id_short(self, value_list, id_short):
        """Find item in value_list by idShort. New AAS_WO model uses ProcessOperationStatus or OperationStatus."""
        candidates = PROPERTY_ALIASES.get(id_short, [id_short])
        for candidate in candidates:
            for item in value_list:
                if isinstance(item, dict) and item.get("idShort") == candidate:
                    return item
        raise KeyError(f"Property '{id_short}' not found (tried {candidates})")

    def _get_submodel_ref_by_id_short(self, shell_id, id_short):
        """Find submodel URN by its idShort (e.g. 'CommonParameter')."""
        refs = self.get_submodel_refs(shell_id)
        shell_enc = base64url_encode(shell_id)
        for sm_ref in refs:
            sm_id = base64url_encode(sm_ref)
            url = self._submodel_url(sm_id, shell_id)
            try:
                resp = requests.get(url, headers=self._headers(), timeout=10)
                if resp.status_code == 200 and resp.content:
                    sm = resp.json()
                    if sm.get("idShort") == id_short:
                        return sm_ref
            except Exception:
                continue
        raise ValueError(f"Submodel with idShort '{id_short}' not found for shell {shell_id}")

    def get_submodel_by_urn(self, shell_id: str, submodel_urn: str) -> dict:
        """Fetch full submodel JSON by shell_id and submodel URN (e.g. BOP)."""
        sm_b64 = base64url_encode(submodel_urn)
        url = self._submodel_url(sm_b64, shell_id)
        resp = requests.get(url, headers=self._headers(), timeout=10)
        resp.raise_for_status()
        if not resp.content:
            raise ValueError(f"Empty response from {url}")
        return resp.json()

    def _get_element_by_path(self, element_id, shell_id=None):
        """Fetch submodel element. Supports 'SubmodelIdShort.ElementPath' or plain element_id."""
        sid = shell_id or self.asset_name
        if "." in element_id:
            parts = element_id.split(".", 1)
            submodel_id_short, elem_path = parts[0], parts[1]
            sm_ref = self._get_submodel_ref_by_id_short(sid, submodel_id_short)
            sm_id = base64url_encode(sm_ref)
            url = self._submodel_url(sm_id, sid, element_path=elem_path)
            resp = requests.get(url, headers=self._headers(), timeout=10)
            resp.raise_for_status()
            if not resp.content:
                raise ValueError(f"Empty response from {url}")
            return resp.json()
        return self.get_asset_submodel_element(element_id)

    def get_property(self, element_id, idShort, shell_id=None):
        """Get a property value from a SubmodelElementCollection.

        Args:
            element_id: Path to the collection containing the property. Use dot notation for
                nested elements (e.g. 'Process_X.MachineDetails' or 'MachineDetails' if top-level).
                Use 'SubmodelIdShort.ElementPath' (e.g. 'CommonParameter.Details') to specify
                submodel by idShort when the interface submodel is not set.
            idShort: Name of the Property within the collection (e.g. 'OperationStatus', 'WorkOrder').
            shell_id: Optional shell ID; defaults to asset_name. Used when element_id is
                'SubmodelIdShort.ElementPath'.
        """
        asset = self._get_element_by_path(element_id, shell_id)
        item = self._find_item_by_id_short(asset["value"], idShort)
        return item.get("value")

    def get_list_item_property(self, element_id, index, idShort, shell_id=None):
        """Get a property from an item in a SubmodelElementList.

        For EnergyConsumption (SubmodelElementList), use index 0 for the first entry (e.g. electricity).
        idShort 'ConsumptionData' returns dict with TotalConsumption and TimeSeriesConsumption.

        Args:
            element_id: Path to the list, e.g. 'EnergyConsumption' (when active_process set),
                'Process_PR_456_on_DMG.EnergyConsumption' (BOP path), or
                'Bill_of_Process.Process_PR_456_on_DMG.EnergyConsumption' (full submodel path).
            index: Zero-based index of the list item.
            idShort: Property name ('TotalConsumption', 'TimeSeriesConsumption'),
                or 'ConsumptionData' for both.
            shell_id: Optional shell ID; defaults to asset_name. Used for dot-notation paths.

        Example:
            afox.set_active_process('Process_PR_456_on_DMG', submodel_id, shell_id)
            total = afox.get_list_item_property('EnergyConsumption', 0, 'TotalConsumption')
            total = bsx.get_list_item_property('Bill_of_Process.Process_PR_456_on_DMG.EnergyConsumption', 0, 'TotalConsumption')
        """
        if self.active_process and self.bop_submodel_id and "." not in element_id:
            url = self._bop_element_url(element_id)
            resp = requests.get(url, headers=self._headers(), timeout=10)
            resp.raise_for_status()
            elem = resp.json() if resp.content else {}
        else:
            elem = self._get_element_by_path(element_id, shell_id)
        entries = elem.get("value", [])
        if index >= len(entries):
            raise IndexError(f"List index {index} out of range (len={len(entries)})")
        item = entries[index]
        props = item.get("value", [])
        if idShort == "ConsumptionData":
            total = next((p.get("value") for p in props if p.get("idShort") == "TotalConsumption"), None)
            timeseries = next((p.get("value") for p in props if p.get("idShort") == "TimeSeriesConsumption"), None)
            return {"TotalConsumption": total, "TimeSeriesConsumption": timeseries}
        p = next((x for x in props if isinstance(x, dict) and x.get("idShort") == idShort), None)
        if p is None:
            raise KeyError(f"Property '{idShort}' not found in list item {index}")
        return p.get("value")

    def set_list_item_property(self, element_id, index, idShort, value, shell_id=None):
        """Set a property in an item of a SubmodelElementList.

        Supports dot notation: 'Bill_of_Process.Process_PR_456_on_DMG.MaterialConsumption'.

        For 'ConsumptionData', value must be a dict with 'TotalConsumption' and/or
        'TimeSeriesConsumption' keys.

        Args:
            element_id: Path to the list (e.g. 'EnergyConsumption',
                'Process_PR_456_on_DMG.EnergyConsumption', or
                'Bill_of_Process.Process_PR_456_on_DMG.MaterialConsumption').
            index: Zero-based index of the list item.
            idShort: Property name, or 'ConsumptionData' to set both.
            value: For 'ConsumptionData': dict like {'TotalConsumption': '12.5',
                'TimeSeriesConsumption': '[0.1,0.2,...]'}. For single property: the value.
            shell_id: Optional shell ID; defaults to asset_name. Used for dot-notation paths.
        """
        put_url = None
        if self.active_process and self.bop_submodel_id and "." not in element_id:
            url = self._bop_element_url(element_id)
            resp = requests.get(url, headers=self._headers(), timeout=10)
            resp.raise_for_status()
            elem = resp.json() if resp.content else {}
            put_url = url
        else:
            elem = self._get_element_by_path(element_id, shell_id)
            if "." in element_id:
                parts = element_id.split(".", 1)
                submodel_id_short, elem_path = parts[0], parts[1]
                sid = shell_id or self.asset_name
                sm_ref = self._get_submodel_ref_by_id_short(sid, submodel_id_short)
                sm_id = base64url_encode(sm_ref)
                put_url = self._submodel_url(sm_id, sid, element_path=elem_path)
        entries = elem.get("value", [])
        if index >= len(entries):
            raise IndexError(f"List index {index} out of range (len={len(entries)})")
        item = entries[index]
        props = item.get("value", [])
        if idShort == "ConsumptionData":
            if not isinstance(value, dict):
                raise TypeError("For 'ConsumptionData', value must be a dict with TotalConsumption and/or TimeSeriesConsumption")
            for p in props:
                if p.get("idShort") == "TotalConsumption" and "TotalConsumption" in value:
                    p["value"] = str(value["TotalConsumption"])
                elif p.get("idShort") == "TimeSeriesConsumption" and "TimeSeriesConsumption" in value:
                    p["value"] = str(value["TimeSeriesConsumption"])
        else:
            p = next((x for x in props if isinstance(x, dict) and x.get("idShort") == idShort), None)
            if p is None:
                raise KeyError(f"Property '{idShort}' not found in list item {index}")
            p["value"] = value
        if put_url:
            resp = requests.put(put_url, headers=self._headers(), json=elem, timeout=10)
            resp.raise_for_status()
        else:
            self.send_request(self.asset_id, self.submodel_id, element_id, body_msg=elem)

    def get_smc_prop(self, element_id, idShort):
        asset = self.get_asset_submodel_element(element_id)
        item = self._find_item_by_id_short(asset["value"], idShort)
        return item.get("value")

    def get_smc_ref(self, element_id, idShort):
        asset = self.get_asset_submodel_element(element_id)
        return next(item for item in asset["value"] if item.get("idShort") == idShort)["value"]['keys'][0]['value']

    def set_smc_prop(self, element_id, idShort, value):
        asset = self.get_asset_submodel_element(element_id)
        self._find_item_by_id_short(asset["value"], idShort)["value"] = value
        self.send_request(self.asset_id, self.submodel_id, element_id, body_msg=asset)

    def set_property(self, element_id, idShort, value, shell_id=None):
        """Set a property value in a SubmodelElementCollection.

        Supports dot notation: 'CommonParameter.Details' to specify submodel by idShort.

        Example:
            bsx.set_property('CommonParameter.Details', 'OperationStatus', 'Ended')
        """
        asset = self._get_element_by_path(element_id, shell_id)
        self._find_item_by_id_short(asset["value"], idShort)["value"] = value
        if "." in element_id:
            parts = element_id.split(".", 1)
            submodel_id_short, elem_path = parts[0], parts[1]
            sid = shell_id or self.asset_name
            sm_ref = self._get_submodel_ref_by_id_short(sid, submodel_id_short)
            sm_id = base64url_encode(sm_ref)
            put_url = self._submodel_url(sm_id, sid, element_path=elem_path)
            resp = requests.put(put_url, headers=self._headers(), json=asset, timeout=10)
            resp.raise_for_status()
        else:
            self.send_request(self.asset_id, self.submodel_id, element_id, body_msg=asset)

    def set_reference(self, element_id, idShort, value):
        asset = self.get_asset_submodel_element(element_id)
        next(i for i in asset["value"] if i["idShort"] == idShort)["value"]["keys"][0]["value"] = value
        self.send_request(self.asset_id, self.submodel_id, element_id, body_msg=asset)

    def send_request(self, asset_id, submodel_id, element_id, body_msg):
        response = requests.put(
            f"{self.base_url}/submodels/{submodel_id}/submodel-elements/{element_id}",
            headers=self._headers(),
            json=body_msg,
            timeout=10,
        )
        response.raise_for_status()
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    # ------------------------------------------------------------------
    # Bill-of-Process (BOP) discovery & process-scoped operations
    # ------------------------------------------------------------------

    def discover_bop_machines(self):
        """Scan all shells for Bill-of-Process submodels and return machines.

        Returns a list of dicts:
            [{"machine_name": "DMG",
              "process_idShort": "Process_PR_456_on_DMG",
              "bop_submodel_id": "urn:submodel:..."}, ...]

        Compatible with BaSyx and AssetFox (same AAS model / AAS_WO JSON).
        """
        shells_data = self.find_shells()
        # BaSyx returns {"result": [...]}, AssetFox returns {"result": [...], "paging_metadata": {...}}
        shells = shells_data.get("result", shells_data) if isinstance(shells_data, dict) else shells_data
        if not isinstance(shells, list):
            shells = []

        machines = []
        for shell_item in shells:
            if isinstance(shell_item, str):
                shell_id_raw = shell_item
            else:
                shell_id_raw = shell_item.get("id") or shell_item.get("idShort") if isinstance(shell_item, dict) else None
            if not shell_id_raw or "WO" not in str(shell_id_raw):
                continue  # Skip non-work-order shells (avoids many HTTP requests)
            if isinstance(shell_item, str):
                try:
                    shell = requests.get(
                        f"{self.registry_base_url}/shells/{base64url_encode(shell_item)}",
                        headers=self._headers(), timeout=10,
                    ).json()
                except Exception:
                    continue
            else:
                shell = shell_item
            if not isinstance(shell, dict):
                continue
            shell_id_enc = base64url_encode(shell_id_raw) if shell_id_raw else None
            for ref in shell.get("submodels", []):
                try:
                    keys = ref.get("keys", [])
                    if not keys:
                        continue
                    sm_raw_id = keys[0].get("value")
                    if not sm_raw_id:
                        continue
                except (KeyError, IndexError, TypeError):
                    continue
                sm_b64 = base64url_encode(sm_raw_id)
                try:
                    # AssetFox: registry/submodels returns HTML; use shell-scoped URL
                    if self.aas_type == 'AAS (AssetFox)' and shell_id_enc:
                        url = f"{self.registry_base_url}/shells/{shell_id_enc}/submodels/{sm_b64}"
                    else:
                        url = f"{self.registry_base_url}/submodels/{sm_b64}"
                    resp = requests.get(url, headers=self._headers(), timeout=10)
                    resp.raise_for_status()
                    sm = resp.json() if resp.content and resp.content.strip().startswith(b'{') else None
                except Exception:
                    continue
                if not sm:
                    continue

                # Both "submodelElements" (AAS 3.0) and "value" (some APIs)
                elems = sm.get("submodelElements", sm.get("value", []))
                if not isinstance(elems, list):
                    continue
                # Case 1: BOP structure - Process_XXX contains MachineDetails (AAS_WO style)
                for elem in elems:
                    if elem.get("modelType") != "SubmodelElementCollection":
                        continue
                    md = next(
                        (c for c in elem.get("value", [])
                         if isinstance(c, dict) and c.get("idShort") == "MachineDetails"),
                        None,
                    )
                    if md is None:
                        continue
                    name = next(
                        (p.get("value") for p in md.get("value", [])
                         if isinstance(p, dict) and p.get("idShort") == "MachineName"),
                        None,
                    )
                    if name:
                        machines.append({
                            "machine_name": name,
                            "process_idShort": elem.get("idShort", ""),
                            "bop_submodel_id": sm_raw_id,
                            "shell_id": shell_id_raw,
                        })
                # Case 2: Direct structure - top-level MachineDetails (same model, AssetFox style)
                md_top = next(
                    (e for e in elems
                     if isinstance(e, dict) and e.get("idShort") == "MachineDetails"
                     and e.get("modelType") == "SubmodelElementCollection"),
                    None,
                )
                if md_top:
                    name = next(
                        (p.get("value") for p in md_top.get("value", [])
                         if isinstance(p, dict) and p.get("idShort") == "MachineName"),
                        None,
                    )
                    if not name:
                        name = next(
                            (p.get("value") for p in md_top.get("value", [])
                             if isinstance(p, dict) and p.get("idShort") == "MachineProgram"),
                            None,
                        )
                    if not name:
                        name = shell.get("idShort") or shell.get("id") or "Default"
                        if name and not any(m["machine_name"] == name and m["bop_submodel_id"] == sm_raw_id and m["process_idShort"] == "" for m in machines):
                            machines.append({
                                "machine_name": str(name),
                                "process_idShort": "",
                                "bop_submodel_id": sm_raw_id,
                                "shell_id": shell_id_raw,
                            })
        # Deduplicate by (machine_name, process_idShort, bop_submodel_id)
        seen = set()
        unique = []
        for m in machines:
            key = (m["machine_name"], m["process_idShort"], m["bop_submodel_id"])
            if key not in seen:
                seen.add(key)
                unique.append(m)
        machines = unique
        # Prefer BOP structure (process_idShort) over direct; dedupe by (shell_id, machine_name)
        # so each shell keeps all its processes (avoids losing processes when multiple shells
        # share the same machine name, e.g. several work orders using "DMG" or "Trumpf")
        def score(m):
            has_bop = 2 if m.get("process_idShort") else 0
            shell_match = 1 if (self.asset_name and m.get("shell_id") == self.asset_name) else 0
            return (has_bop, shell_match)

        by_shell_machine = {}
        for m in machines:
            key = (m.get("shell_id"), m["machine_name"])
            if key not in by_shell_machine or score(m) > score(by_shell_machine[key]):
                by_shell_machine[key] = m
        machines = list(by_shell_machine.values())
        # If we have BOP machines (DMG, Trumpf from AAS_WO), return only those for consistency
        bop_only = [m for m in machines if m["process_idShort"]]
        if bop_only:
            machines = bop_only
        # Fallback: when no machines found (e.g. AssetFox different shell structure),
        # explicitly check the configured asset's submodels (same model as BaSyx)
        if not machines and self.asset_name:
            try:
                shell = self.get_shell_asset(self.asset_name)
                for ref in shell.get("submodels", []):
                    try:
                        sm_raw_id = ref.get("keys", [{}])[0].get("value")
                        if not sm_raw_id:
                            continue
                    except (KeyError, IndexError, TypeError):
                        continue
                    sm_b64 = base64url_encode(sm_raw_id)
                    try:
                        # AssetFox: try shell-scoped URL first (base_url), then registry
                        url = f"{self.base_url}/submodels/{sm_b64}"
                        resp = requests.get(url, headers=self._headers(), timeout=10)
                        if resp.status_code == 404 or (resp.status_code == 200 and not resp.content):
                            url = f"{self.registry_base_url}/submodels/{sm_b64}"
                            resp = requests.get(url, headers=self._headers(), timeout=10)
                        resp.raise_for_status()
                        sm = resp.json() if resp.content else None
                    except Exception:
                        continue
                    if not sm:
                        continue
                    elems = sm.get("submodelElements", sm.get("value", []))
                    if not isinstance(elems, list):
                        continue
                    for elem in elems:
                        if elem.get("modelType") != "SubmodelElementCollection":
                            continue
                        md = next(
                            (c for c in elem.get("value", [])
                             if isinstance(c, dict) and c.get("idShort") == "MachineDetails"),
                            None,
                        )
                        if md is None:
                            continue
                        name = next(
                            (p.get("value") for p in md.get("value", [])
                             if isinstance(p, dict) and p.get("idShort") == "MachineName"),
                            None,
                        )
                        if name:
                            machines.append({
                                "machine_name": name,
                                "process_idShort": elem.get("idShort", ""),
                                "bop_submodel_id": sm_raw_id,
                                "shell_id": shell.get("id") or shell.get("idShort") or self.asset_name,
                            })
                    # Case 2: Top-level MachineDetails (direct structure, same model)
                    md_top = next(
                        (e for e in elems if isinstance(e, dict) and e.get("idShort") == "MachineDetails"
                         and e.get("modelType") == "SubmodelElementCollection"),
                        None,
                    )
                    if md_top:
                        name = next(
                            (p.get("value") for p in md_top.get("value", [])
                             if isinstance(p, dict) and p.get("idShort") == "MachineName"),
                            None,
                        )
                        if not name:
                            name = next(
                                (p.get("value") for p in md_top.get("value", [])
                                 if isinstance(p, dict) and p.get("idShort") == "MachineProgram"),
                                None,
                            )
                        if not name:
                            name = shell.get("idShort") or shell.get("id") or "Default"
                        if name and not any(m["machine_name"] == name and m["bop_submodel_id"] == sm_raw_id for m in machines):
                            machines.append({
                                "machine_name": str(name),
                                "process_idShort": "",
                                "bop_submodel_id": sm_raw_id,
                                "shell_id": shell.get("id") or shell.get("idShort") or self.asset_name,
                            })
            except Exception:
                pass
        return machines

    def set_active_process(self, process_idShort, bop_submodel_id, shell_id=None):
        """Select the BOP process element used by subsequent process-scoped calls.

        For AssetFox, shell_id is required for shell-scoped submodel URLs.
        When shell_id is missing, falls back to asset_name (configured work order) for AssetFox.
        """
        self.active_process = process_idShort
        self.bop_submodel_id = base64url_encode(bop_submodel_id)
        # AssetFox requires shell-scoped URLs; registry-level /submodels returns HTML
        resolved_shell = shell_id
        if self.aas_type == 'AAS (AssetFox)' and not resolved_shell and self.asset_name:
            resolved_shell = self.asset_name  # Fallback: use configured work order as shell
        self.bop_shell_id = base64url_encode(resolved_shell) if resolved_shell else None

    def _bop_element_url(self, element_id):
        # Direct structure (top-level MachineDetails): active_process is ""
        path = f"{self.active_process}.{element_id}" if self.active_process else element_id
        # AssetFox: registry/submodels returns HTML; use shell-scoped URL
        if self.aas_type == 'AAS (AssetFox)' and getattr(self, 'bop_shell_id', None):
            return f"{self.registry_base_url}/shells/{self.bop_shell_id}/submodels/{self.bop_submodel_id}/submodel-elements/{path}"
        return f"{self.registry_base_url}/submodels/{self.bop_submodel_id}/submodel-elements/{path}"

    def _element_url(self, element_id):
        """URL for a submodel element. Uses BOP submodel when active_process set, else main submodel (direct mode)."""
        if self.active_process and self.bop_submodel_id:
            return self._bop_element_url(element_id)
        # Direct mode: main submodel (same URL pattern as get_asset_submodel_element)
        url = f"{self.base_url}/submodels/{self.submodel_id}/submodel-elements/{element_id}"
        return url

    def get_process_property(self, element_id, idShort):
        """Read a property from a collection inside the active BOP process."""
        resp = requests.get(
            self._bop_element_url(element_id),
            headers=self._headers(), timeout=10,
        )
        resp.raise_for_status()
        asset = resp.json()
        item = self._find_item_by_id_short(asset["value"], idShort)
        return item.get("value")

    def set_process_property(self, element_id, idShort, value):
        """Write a property in a collection inside the active BOP process."""
        url = self._bop_element_url(element_id)
        resp = requests.get(url, headers=self._headers(), timeout=10)
        resp.raise_for_status()
        asset = resp.json()
        self._find_item_by_id_short(asset["value"], idShort)["value"] = value
        resp = requests.put(url, headers=self._headers(), json=asset, timeout=10)
        resp.raise_for_status()

    def update_energy_consumption(self, energy_updates):
        """Update EnergyConsumption list: TotalConsumption, TimeSeriesConsumption, EnergyConsumptionDataPointId per entry.

        energy_updates: list of dicts, each with keys:
            - name: "electricity" or "CompressedAir" (matches Name property in AAS)
            - total_consumption: float/str
            - time_series_str: e.g. "[0.1,0.2,...]"
            - data_point_id: IIH attribute UUID (optional, sets EnergyConsumptionDataPointId)
        """
        url = self._element_url("EnergyConsumption")
        resp = requests.get(url, headers=self._headers(), timeout=10)
        if self.aas_type == "AAS (AssetFox)" and (resp.status_code == 404 or not resp.content):
            # Try shell-scoped URL first (AssetFox registry/submodels returns HTML)
            if getattr(self, "bop_shell_id", None) and getattr(self, "bop_submodel_id", None):
                alt_url = f"{self.registry_base_url}/shells/{self.bop_shell_id}/submodels/{self.bop_submodel_id}/submodel-elements/EnergyConsumption"
                alt_resp = requests.get(alt_url, headers=self._headers(), timeout=10)
                if alt_resp.status_code == 200 and alt_resp.content:
                    url, resp = alt_url, alt_resp
            if resp.status_code == 404 or not resp.content:
                alt_url = f"{self.registry_base_url}/submodels/{self.submodel_id}/submodel-elements/EnergyConsumption"
                alt_resp = requests.get(alt_url, headers=self._headers(), timeout=10)
                if alt_resp.status_code == 200 and alt_resp.content:
                    url, resp = alt_url, alt_resp
        resp.raise_for_status()
        energy_list = resp.json()
        updates_by_name = {u["name"]: u for u in energy_updates}
        entries = energy_list.get("value", [])
        if not isinstance(entries, list):
            entries = []

        # Collect which entry names already exist (normalize for AssetFox "Compressed Air" vs "CompressedAir")
        existing_names = set()
        for entry in entries:
            entry_name = next(
                (p.get("value") for p in entry.get("value", [])
                 if isinstance(p, dict) and p.get("idShort") == "Name"),
                None,
            )
            if entry_name:
                existing_names.add(_normalize_energy_name(entry_name))

        for entry in entries:
            entry_name = next(
                (p.get("value") for p in entry.get("value", [])
                 if isinstance(p, dict) and p.get("idShort") == "Name"),
                None,
            )
            canonical = _normalize_energy_name(entry_name) if entry_name else None
            if not canonical or canonical not in updates_by_name:
                continue
            upd = updates_by_name[canonical]
            data_point_id_prop = None
            props = entry.get("value", [])
            for prop in props:
                if prop.get("idShort") == "TotalConsumption":
                    prop["value"] = str(upd["total_consumption"])
                elif prop.get("idShort") == "TimeSeriesConsumption":
                    prop["value"] = upd["time_series_str"]
                elif prop.get("idShort") == "EnergyConsumptionDataPointId":
                    data_point_id_prop = prop
                    if upd.get("data_point_id"):
                        prop["value"] = str(upd["data_point_id"])

            # Electricity entry often has EnergyConsumptionDataPointId omitted by server when empty.
            # Add the property if missing but we have data_point_id (insert after Unit to match template).
            if upd.get("data_point_id") and data_point_id_prop is None:
                new_prop = {
                    "idShort": "EnergyConsumptionDataPointId",
                    "valueType": "xs:string",
                    "value": str(upd["data_point_id"]),
                    "modelType": "Property",
                }
                insert_after = next(
                    (i for i, p in enumerate(props) if isinstance(p, dict) and p.get("idShort") == "Unit"),
                    -1,
                )
                props.insert(insert_after + 1, new_prop)

        # AssetFox (and some work orders) may only have electricity in EnergyConsumption.
        # Append missing entries (e.g. CompressedAir) when we have data for them.
        _unit_map = {"electricity": "kWh", "CompressedAir": "M3"}
        for name, upd in updates_by_name.items():
            if name in existing_names:
                continue
            unit = _unit_map.get(name, "unknown")
            dp_id = str(upd.get("data_point_id", "")) if upd.get("data_point_id") else ""
            new_entry = {
                "modelType": "SubmodelElementCollection",
                "value": [
                    {"idShort": "Name", "valueType": "xs:string", "value": name, "modelType": "Property"},
                    {"idShort": "TotalConsumption", "valueType": "xs:string", "value": str(upd["total_consumption"]), "modelType": "Property"},
                    {"idShort": "TimeSeriesConsumption", "valueType": "xs:string", "value": upd["time_series_str"], "modelType": "Property"},
                    {"idShort": "Unit", "valueType": "xs:string", "value": unit, "modelType": "Property"},
                    {"idShort": "EnergyConsumptionDataPointId", "valueType": "xs:string", "value": dp_id, "modelType": "Property"},
                    {"idShort": "AvgEmissionFactor", "valueType": "xs:float", "value": "0.0", "modelType": "Property"},
                    {"idShort": "EnergyConsumptionCarbonFootprint", "valueType": "xs:float", "value": "0", "modelType": "Property"},
                ],
            }
            entries.append(new_entry)

        energy_list["value"] = entries
        resp = requests.put(url, headers=self._headers(), json=energy_list, timeout=10)
        resp.raise_for_status()



