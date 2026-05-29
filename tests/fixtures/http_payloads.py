# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0

op_1 = {
  "workOrderName": "PO_40003",
  "workOrderOperationName": "OP10-Fraesen",
  "workUnit": "DMG-WorkUnit-1",
  "consumedMaterials": [
    {
      "identifier": "Aluprofil-001",
      "materialName": "Aluprofil-001",
      "quantity": 150,
      "materialUom": "mm"
    }
  ],
  "consumedEnergies": [
    {
      "type": "Electricity",
      "uom": "kWh",
      "resourceUsage": {
        "measurementType": "DELTA",
        "measurements": [
          {
            "start": "2025-06-16T16:05:00Z",
            "duration": "15",
            "consumption": 12
          },
          {
            "start": "2025-06-16T16:20:00Z",
            "duration": "15",
            "consumption": 70
          },
          {
            "start": "2025-06-16T16:35:00Z",
            "duration": "15",
            "consumption": 230
          },
          {
            "start": "2025-05-19T08:50:00Z",
            "duration": "3",
            "consumption": 7
          }
        ]
      }
    }
  ],
  "actualStartTime": "2025-06-16T16:05:00Z",
  "actualEndTime": "2025-06-16T16:53:00Z",
  "timestamp": "2025-06-16T17:00:00Z"
}



op_2 = {
  "workOrderName": "PO_40003",
  "workOrderOperationName": "OP20-Laesern",
  "workUnit": "Trumpf-WorkUnit-1",
  "consumedEnergies": [
    {
      "type": "Electricity",
      "uom": "kWh",
      "resourceUsage": {
        "measurementType": "DELTA",
        "measurements": [
          {
            "start": "2025-06-16T16:59:00Z",
            "duration": "1",
            "consumption": 5
          }
        ]
      }
    }
  ],
  "actualStartTime": "2025-06-16T16:59:00Z",
  "actualEndTime": "2025-06-16T17:00:00Z",
  "timestamp": "2025-06-16T17:01:00Z"
}


op_3 = {
  "workOrderName": "PO_40003",
  "workOrderOperationName": "OP30-Assembly",
  "workUnit": "Assembly-WorkUnit-1",
  "consumedMaterials": [
    {
      "identifier": "Blechwinkel-15x10",
      "materialName": "Blechwinkel 15x10 mm",
      "quantity": 2,
      "materialUom": "piece"
    },
    {
      "identifier": "Schrauben M6",
      "materialName": "Schrauben M6",
      "quantity": 2,
      "materialUom": "piece"
    }
  ],
  "actualStartTime": "2025-06-16T17:20:00Z",
  "actualEndTime": "2025-06-16T17:30:00Z",
  "timestamp": "2025-06-16T17:31:00Z"
}


op_4 = {
  "workOrderName": "PO_40003",
  "workOrderOperationName": "OP40-Packaging",
  "workUnit": "Packaging-WorkUnit-1",
  "consumedMaterials": [
    {
      "identifier": "PneumaticConnection_Festo",
      "materialName": "PneumaticConnection_Festo",
      "quantity": 1,
      "materialUom": "piece"
    },
    {
      "identifier": "Screw_M6",
      "materialName": "Screw_M6",
      "quantity": 2,
      "materialUom": "piece"
    },
    {
      "identifier": "PackagingBox_Size15",
      "materialName": "PackagingBox_Size15",
      "quantity": 1,
      "materialUom": "piece"
    }  ],
  "actualStartTime": "2025-06-16T17:41:00Z",
  "actualEndTime": "2025-06-16T17:49:00Z",
  "timestamp": "2025-06-16T17:50:00Z"
}



prod_result_1 = {
  "workOrderName": "PO_40003",
  "workOrderState": "Completed",
  "productId": "Greiferbacken-Typ-A",
  "productName": "Greiferbacken-Typ-A",
  "productRevision": "0",
  "traceabilityType": "Serial Number",
  "producedMtus": [
    "SN-40003.01"
  ],
  "uom": "pieces",
  "producedQuantity": 1,
  "scrappedQuantity": 0,
  "actualStartTime": "2025-06-16T16:05:00Z",
  "actualEndTime": "2025-06-16T17:49:00Z",
  "locationName": "FX-GripperHousing-JGPP40-Produktion",
  "timestamp": "2025-06-16T17:51:00Z"
}


# WO-0009: EngineBlock scenario ------------------------------------------------

# PO_8886 OP20-Laesern: Electricity + CompressedAir (for CompressedAir carbon footprint test)
op_compressed_air = {
    "workOrderName": "PO_8886",
    "workOrderOperationName": "OP20-Laesern",
    "workUnit": "Trumpf-WorkUnit-1",
    "consumedEnergies": [
        {
            "type": "Electricity",
            "uom": "kWh",
            "resourceUsage": {
                "measurementType": "DELTA",
                "measurements": [
                    {
                        "start": "2025-06-16T16:59:00Z",
                        "duration": "1",
                        "consumption": 5
                    }
                ]
            }
        },
        {
            "type": "CompressedAir",
            "uom": "M3",
            "resourceUsage": {
                "measurementType": "DELTA",
                "measurements": [
                    {
                        "start": "2025-06-16T16:59:00Z",
                        "duration": "1",
                        "consumption": 5
                    }
                ]
            }
        }
    ],
    "actualStartTime": "2025-06-16T16:59:00Z",
    "actualEndTime": "2025-06-16T17:00:00Z",
    "timestamp": "2025-06-16T17:01:00Z"
}


wo9_consumption = {
  "workOrderName": "WO-0009",
  "workOrderOperationName": "OP10-Fraesen",
  "workUnit": "DMG-WorkUnit-1",
  "consumedMaterials": [
    {
      "identifier": "Aluprofil-001",
      "materialName": "Aluprofil-001",
      "quantity": 150,
      "materialUom": "mm"
    },
    {
      "identifier": "Screw_M6",
      "materialName": "Screw_M6",
      "quantity": 2,
      "materialUom": "piece"
    }
  ],
  "consumedEnergies": [
    {
      "type": "Electricity",
      "uom": "kWh",
      "resourceUsage": {
        "measurementType": "DELTA",
        "measurements": [
          {"start": "2026-03-05T15:48:36Z", "duration": "15", "consumption": 12},
          {"start": "2026-03-05T15:50:00Z", "duration": "15", "consumption": 70},
          {"start": "2026-03-05T15:51:00Z", "duration": "15", "consumption": 230},
          {"start": "2026-03-05T15:52:00Z", "duration": "3",  "consumption": 7}
        ]
      }
    }
  ],
  "actualStartTime": "2026-03-05T15:48:36Z",
  "actualEndTime": "2026-03-05T15:52:19Z",
  "timestamp": "2026-03-05T15:52:30Z"
}


wo9_prod_result = {
  "workOrderName": "WO-0009",
  "workOrderState": "Completed",
  "productId": "EngineBlock",
  "productName": "EngineBlock",
  "locationName": "Bonn",
  "uom": "pieces",
  "traceabilityType": "Untraceable",
  "productRevision": "A",
  "producedQuantity": 1.0,
  "scrappedQuantity": 0.0,
  "actualStartTime": "2026-03-05T15:48:36Z",
  "actualEndTime": "2026-03-05T15:52:19Z",
  "producedMtus": ["WO-0009"],
  "timestamp": "2026-03-05T15:53:03Z"
}
