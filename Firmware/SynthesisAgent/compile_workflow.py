import json
import argparse
import pandas as pd
from pathlib import Path
import uuid
from typing import Any, Dict, List


def nid(prefix: str) -> str:
    """Generate a short unique identifier with a prefix."""
    return f"{prefix}{uuid.uuid4().hex[:8]}"


def as_project_rows(
    vol_df: pd.DataFrame, bottle_order: List[str]
) -> List[Dict[str, Any]]:
    """Convert CSV rows to project list for liquid dispensing."""
    rows: List[Dict[str, Any]] = []
    for row_idx, row in vol_df.iterrows():
        entry: Dict[str, Any] = {"tube_num": int(row_idx) + 1, "cap": "1"}
        for b_i, col in enumerate(bottle_order):
            val = row.get(col, 0)
            if pd.isna(val):
                val = 0
            entry[f"bottle{b_i}"] = float(val)
        for b_i in range(len(bottle_order), 8):
            entry[f"bottle{b_i}"] = 0
        rows.append(entry)
    return rows


def alloc_containers(
    count: int,
    code: str = "bottle_storage",
    name: str = "进样瓶",
    mode: str = "extend",
    start_logic_no: int = 1,
) -> List[Dict[str, Any]]:
    """Create container allocation structure."""
    selected = [
        {"logicNo": i, "selected": True}
        for i in range(start_logic_no, start_logic_no + max(count, 1))
    ]
    return [
        {
            "containerCount": count,
            "containerTypeCode": code,
            "containerTypeName": name,
            "allocateMode": mode,
            "selectedContainers": selected,
        }
    ]


TEMPLATES: Dict[str, Dict[str, Any]] = {
    "starting_station_take": {
        "stepType": "workstation",
        "workstationType": "starting_station",
        "workstationTypeName": "物料站",
        "definitionVersion": "303物料站",
        "pipeline": "common_take_flow",
        "actionParams": [],
        "container": {"allocation": alloc_containers(2, mode="new")},
    },
    "starting_station_put": {
        "stepType": "workstation",
        "workstationType": "starting_station",
        "workstationTypeName": "物料站",
        "definitionVersion": "303物料站",
        "pipeline": "common_put_flow",
        "actionParams": [],
        "container": {"allocation": alloc_containers(2, mode="new")},
    },
    "liquid_dispensing": {
        "stepType": "workstation",
        "workstationType": "liquid_dispensing",
        "workstationTypeName": "液体进样站",
        "definitionVersion": "移液平台2.0-不嵌套",
        "pipeline": "multi_add_flow",
    },
    "magnetic_stirring": {
        "stepType": "workstation",
        "workstationType": "magnetic_stirring",
        "workstationTypeName": "磁力搅拌工作站",
        "definitionVersion": "303-25通道磁力搅拌控制器",
        "pipeline": "multi_main_flow",
    },
    "ultrasonic_cleaning": {
        "stepType": "workstation",
        "workstationType": "ultrasonic_cleaning",
        "workstationTypeName": "超声清洗",
        "definitionVersion": "1.0",
        "pipeline": "multi_main_flow",
    },
    "dryer": {
        "stepType": "workstation",
        "workstationType": "dryer",
        "workstationTypeName": "烘干机",
        "definitionVersion": "gxq_1.0",
        "pipeline": "multi_main_flow",
    },
    "pure": {
        "stepType": "workstation",
        "workstationType": "pure",
        "workstationTypeName": "纯化工作站",
        "definitionVersion": "1.0",
        "pipeline": "new_pure_flow",
    },
    "dual_electrochemical": {
        "stepType": "workstation",
        "workstationType": "dual_electrochemical",
        "workstationTypeName": "双工位电化学工作站",
        "definitionVersion": "2.0",
        "pipeline": "multi_main_flow",
    },
    "start_ctrl": {
        "stepType": "ProcessControl",
        "workstationType": "start",
        "workstationTypeName": "开始",
        "definitionVersion": None,
        "pipeline": None,
        "actionParams": [],
        "container": None,
    },
    "end_ctrl": {
        "stepType": "ProcessControl",
        "workstationType": "end",
        "workstationTypeName": "结束",
        "definitionVersion": None,
        "pipeline": None,
        "actionParams": [],
        "container": None,
    },
}


def build_liquid_node(project_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    node = {**TEMPLATES["liquid_dispensing"]}
    node["actionParams"] = [
        {
            "actionCode": "add_liquid",
            "key": "add_liquid",
            "params": [
                {
                    "paramCode": "project",
                    "value": json.dumps(project_rows, ensure_ascii=False),
                },
            ],
        }
    ]
    node["container"] = {"allocation": alloc_containers(2)}
    return node


def build_stir_node(mixing_time_min: int) -> Dict[str, Any]:
    node = {**TEMPLATES["magnetic_stirring"]}
    node["actionParams"] = [
        {
            "actionCode": "mixing_time",
            "key": "mixing_time",
            "params": [
                {
                    "paramCode": "mixing_time",
                    "value": str(int(mixing_time_min)),
                },
            ],
        }
    ]
    node["container"] = {"allocation": alloc_containers(2)}
    return node


def build_ultrasonic_node(duration_min: int) -> Dict[str, Any]:
    node = {**TEMPLATES["ultrasonic_cleaning"]}
    node["actionParams"] = [
        {
            "actionCode": "start_clean",
            "key": "start_clean",
            "params": [
                {
                    "paramCode": "value",
                    # platform expects seconds
                    "value": str(int(duration_min) * 60),
                },
            ],
        }
    ]
    node["container"] = {"allocation": alloc_containers(1)}
    return node


def build_dryer_node(
    temperature_C: int, duration_min: int, sealed: bool
) -> Dict[str, Any]:
    """Construct a dryer node with temperature, duration and optional sealed flag."""
    node = {**TEMPLATES["dryer"]}
    actions = [
        {
            "actionCode": "close-door",
            "key": "close-door",
            "params": [
                {"paramCode": "temperature", "value": str(int(temperature_C))},
            ],
        },
        {
            "actionCode": "pure_dry",
            "key": "pure_dry",
            "params": [
                {"paramCode": "time", "value": str(int(duration_min))},
            ],
        },
        {
            "actionCode": "close-door",
            "key": "close-door_2",
            "params": [
                {"paramCode": "temperature", "value": str(int(temperature_C))},
            ],
        },
    ]
    if sealed:
        actions.append(
            {
                "actionCode": "seal",
                "key": "seal",
                "params": [
                    {"paramCode": "status", "value": "1"},
                ],
            }
        )
    node["actionParams"] = actions
    node["container"] = {"allocation": alloc_containers(1)}
    return node


def build_pure_node(
    speed_rpm: int, duration_min: int, wash_times: int, retain_phase: str
) -> Dict[str, Any]:
    """Construct a centrifuge purification node."""
    node = {**TEMPLATES["pure"]}
    retain_supernatant = retain_phase == "supernatant"
    node["actionParams"] = [
        {
            "actionCode": "start",
            "key": "start",
            "params": [
                {"paramCode": "program", "value": "2"},
                {"paramCode": "time", "value": str(int(duration_min))},
                {"paramCode": "speed", "value": str(int(speed_rpm))},
                {"paramCode": "cleanNum", "value": str(int(wash_times))},
                # washSolutions: define default wash solution (1)
                {
                    "paramCode": "washSolutions",
                    "value": json.dumps([{"washSolution": 1}], ensure_ascii=False),
                },
                {"paramCode": "autoStatus", "value": "1"},
                {"paramCode": "addLiquidNum", "value": "5"},
                {
                    "paramCode": "isLeaveWashSolution",
                    "value": "1" if retain_supernatant else "0",
                },
                {
                    "paramCode": "leaveParam",
                    "value": json.dumps(
                        {"leaveLiquidAmount": "10", "washSolution": "1"},
                        ensure_ascii=False,
                    ),
                },
            ],
        }
    ]
    # allocate sample bottle and retention bottle
    node["container"] = {
        "allocation": alloc_containers(1)
        + alloc_containers(1, code="bottle_sample_retention", name="留样瓶")
    }
    return node


def build_echem_node(test_types: List[str]) -> Dict[str, Any]:
    """Construct a dual electrochemical workstation node for given test types."""
    # build test templates based on requested test types
    tests: List[Dict[str, Any]] = []
    order = 0
    for tt in test_types:
        tt_upper = tt.upper()
        if tt_upper == "LSV":
            tests.append(
                {
                    "order": order,
                    "workDetectionType": "linearSweepVoltammetry",
                    "param": {
                        "initE": "0",
                        "finalE": "0.8",
                        "scanRate": "0.05",
                        "sampleInterval": "0.001",
                        "quietTime": "2",
                        "sensitivity": "1e-001",
                    },
                }
            )
            order += 1
        elif tt_upper == "CV":
            tests.append(
                {
                    "order": order,
                    "workDetectionType": "cyclicVoltammetry",
                    "param": {
                        "initE": "0",
                        "highE": "0.8",
                        "lowE": "0",
                        "cycle": "2",
                        "scanRate": "0.05",
                        "quietTime": "2",
                    },
                }
            )
            order += 1
        elif tt_upper == "EIS":
            tests.append(
                {
                    "order": order,
                    "workDetectionType": "electrochemicalImpedanceSpectroscopy",
                    "param": {
                        "startFreq": "100000",
                        "endFreq": "0.1",
                        "acAmplitude": "0.01",
                    },
                }
            )
            order += 1
    # baseline tasks: enable taskOne, disable others
    task_params = []
    # first task (enabled)
    task_params.append(
        {
            "paramCode": "taskOne",
            "value": json.dumps(
                {
                    "isStart": "true",
                    "sampleInjectionBottle": 1,
                    "retentionSampleBottle": "",
                    "catalystDropletVolume": 50,
                    "electrolyteAdditionAmount": 20,
                    "carbonPaperOperateTime": 30,
                    "cleaningFrequency": 3,
                    "carbonPaperType": "hydrophilicity",
                    "ventilationStatus": "none",
                    "ventilationDuration": "1",
                    "velocityFlow": "3",
                    "magneticStirringSpeed": 500,
                },
                ensure_ascii=False,
            ),
        }
    )
    # tasks Two through Ten (disabled)
    for suffix in [
        "Two",
        "Three",
        "Four",
        "Five",
        "Six",
        "Seven",
        "Eight",
        "Nine",
        "Ten",
    ]:
        task_params.append(
            {
                "paramCode": f"task{suffix}",
                "value": json.dumps(
                    {
                        "isStart": "false",
                        "sampleInjectionBottle": "",
                        "retentionSampleBottle": "",
                        "catalystDropletVolume": 100,
                        "electrolyteAdditionAmount": 20,
                        "carbonPaperOperateTime": 10,
                        "cleaningFrequency": 3,
                        "carbonPaperType": "hydrophilicity",
                        "ventilationStatus": "none",
                        "ventilationDuration": "1",
                        "velocityFlow": "3",
                        "magneticStirringSpeed": 350,
                    },
                    ensure_ascii=False,
                ),
            }
        )
    node = {**TEMPLATES["dual_electrochemical"]}
    node["actionParams"] = [
        {
            "actionCode": "chemicalTest",
            "key": "chemicalTest",
            "params": [
                {"paramCode": "bottleType", "value": "uncapScrewBottle"},
                {"paramCode": "cathodePoolOperate", "value": "no"},
                {"paramCode": "cathodePoolRetentionVolume", "value": "10"},
                {"paramCode": "carbonPaperOperate", "value": "heat"},
                {"paramCode": "carbonPaperOperateTemperature", "value": "60"},
                {"paramCode": "liquidFill", "value": "no"},
                # add the tasks definitions
                *task_params,
                {
                    "paramCode": "testTemplate",
                    "value": json.dumps(
                        [
                            {
                                "id": 1549499770798080,
                                "modelName": "智能数据调试",
                                "modelValue": tests,
                            }
                        ],
                        ensure_ascii=False,
                    ),
                },
            ],
        }
    ]
    node["container"] = {"allocation": alloc_containers(1)}
    return node


def compile_to_fixed(workflow: Dict[str, Any], csv_path: Path) -> Dict[str, Any]:
    """
    Compile a simplified workflow into a detailed fixed workflow definition.
    This adds start/end nodes, material stations, and appropriate workstation
    steps based on the provided step definitions and CSV parameters.
    """
    # load CSV
    df = pd.read_csv(csv_path) if csv_path else pd.DataFrame()
    if "Index" in df.columns:
        df = df.drop(columns=["Index"])
    bottle_cols = list(df.columns)

    # initialize start/end and material station nodes
    start_id = "开始节点id"
    end_id = "结束节点id"
    start_ws_node_id = "物料站0节点id"
    end_ws_node_id = "物料站1节点id"

    nodeMap: Dict[str, Dict[str, Any]] = {
        start_id: {
            "nodeId": start_id,
            "dataId": "开始节点属性",
            "stepType": "ProcessControl",
            "workstationType": "start",
            "workstationTypeName": "开始",
        },
        end_id: {
            "nodeId": end_id,
            "dataId": "结束节点属性",
            "stepType": "ProcessControl",
            "workstationType": "end",
            "workstationTypeName": "结束",
        },
        start_ws_node_id: {
            "nodeId": start_ws_node_id,
            "dataId": "物料站0节点属性",
            "stepType": "workstation",
            "workstationType": "starting_station",
            "workstationTypeName": "物料站",
        },
        end_ws_node_id: {
            "nodeId": end_ws_node_id,
            "dataId": "物料站1节点属性",
            "stepType": "workstation",
            "workstationType": "starting_station",
            "workstationTypeName": "物料站",
        },
    }
    dataMap: Dict[str, Dict[str, Any]] = {
        "开始节点属性": {**TEMPLATES["start_ctrl"], "dataId": "开始节点属性"},
        "结束节点属性": {**TEMPLATES["end_ctrl"], "dataId": "结束节点属性"},
        "物料站0节点属性": {
            **TEMPLATES["starting_station_take"],
            "dataId": "物料站0节点属性",
        },
        "物料站1节点属性": {
            **TEMPLATES["starting_station_put"],
            "dataId": "物料站1节点属性",
        },
    }
    path: Dict[str, str] = {start_id: start_ws_node_id}
    prev_node_id = start_ws_node_id

    # compile steps into nodes and connect them
    for step in workflow.get("input", {}).get("steps", []):
        ws_id = step.get("workstation_id")
        sid = step.get("step_id")
        params = step.get("parameters", {})
        # create nodes depending on workstation
        if ws_id == "solution-preparation":
            # first add liquid dispensing
            liquid_node_id = f"液体进样站{sid}节点id"
            liquid_data_id = f"液体进样站{sid}节点属性"
            nodeMap[liquid_node_id] = {
                "nodeId": liquid_node_id,
                "dataId": liquid_data_id,
                "stepType": "workstation",
                "workstationType": "liquid_dispensing",
                "workstationTypeName": "液体进样站",
            }
            project_rows = as_project_rows(df, bottle_cols)
            dataMap[liquid_data_id] = {
                **build_liquid_node(project_rows),
                "dataId": liquid_data_id,
            }
            # connect
            path[prev_node_id] = liquid_node_id
            prev_node_id = liquid_node_id
            # second add stirring if mixing_time_min provided
            if params.get("mixing_time_min") is not None:
                stir_node_id = f"磁力搅拌工作站{sid}节点id"
                stir_data_id = f"磁力搅拌工作站{sid}节点属性"
                nodeMap[stir_node_id] = {
                    "nodeId": stir_node_id,
                    "dataId": stir_data_id,
                    "stepType": "workstation",
                    "workstationType": "magnetic_stirring",
                    "workstationTypeName": "磁力搅拌工作站",
                }
                dataMap[stir_data_id] = {
                    **build_stir_node(int(params["mixing_time_min"])),
                    "dataId": stir_data_id,
                }
                path[prev_node_id] = stir_node_id
                prev_node_id = stir_node_id
        elif ws_id == "ultrasonic-treatment":
            u_node_id = f"超声清洗{sid}节点id"
            u_data_id = f"超声清洗{sid}节点属性"
            nodeMap[u_node_id] = {
                "nodeId": u_node_id,
                "dataId": u_data_id,
                "stepType": "workstation",
                "workstationType": "ultrasonic_cleaning",
                "workstationTypeName": "超声清洗",
            }
            dataMap[u_data_id] = {
                **build_ultrasonic_node(int(params.get("duration_min", 0))),
                "dataId": u_data_id,
            }
            path[prev_node_id] = u_node_id
            prev_node_id = u_node_id
        elif ws_id == "oven-station":
            d_node_id = f"烘干机{sid}节点id"
            d_data_id = f"烘干机{sid}节点属性"
            nodeMap[d_node_id] = {
                "nodeId": d_node_id,
                "dataId": d_data_id,
                "stepType": "workstation",
                "workstationType": "dryer",
                "workstationTypeName": "烘干机",
            }
            dataMap[d_data_id] = {
                **build_dryer_node(
                    int(params.get("temperature_C", 0)),
                    int(params.get("duration_min", 0)),
                    bool(params.get("sealed", False)),
                ),
                "dataId": d_data_id,
            }
            path[prev_node_id] = d_node_id
            prev_node_id = d_node_id
        elif ws_id == "centrifuge-purification":
            p_node_id = f"纯化工作站{sid}节点id"
            p_data_id = f"纯化工作站{sid}节点属性"
            nodeMap[p_node_id] = {
                "nodeId": p_node_id,
                "dataId": p_data_id,
                "stepType": "workstation",
                "workstationType": "pure",
                "workstationTypeName": "纯化工作站",
            }
            dataMap[p_data_id] = {
                **build_pure_node(
                    int(params.get("speed_rpm", 0)),
                    int(params.get("duration_min", 0)),
                    int(params.get("wash_times", 0)),
                    params.get("retain_phase", "precipitate"),
                ),
                "dataId": p_data_id,
            }
            path[prev_node_id] = p_node_id
            prev_node_id = p_node_id
        elif ws_id == "electrochemistry-station":
            e_node_id = f"双工位电化学工作站{sid}节点id"
            e_data_id = f"双工位电化学工作站{sid}节点属性"
            nodeMap[e_node_id] = {
                "nodeId": e_node_id,
                "dataId": e_data_id,
                "stepType": "workstation",
                "workstationType": "dual_electrochemical",
                "workstationTypeName": "双工位电化学工作站",
            }
            dataMap[e_data_id] = {
                **build_echem_node(list(params.get("test_types", []))),
                "dataId": e_data_id,
            }
            path[prev_node_id] = e_node_id
            prev_node_id = e_node_id
        else:
            raise ValueError(f"Unsupported workstation_id: {ws_id}")

    # connect final steps to material station and end
    path[prev_node_id] = end_ws_node_id
    path[end_ws_node_id] = end_id

    return {
        "startNodeId": start_id,
        "endNodeId": end_id,
        "nodeMap": nodeMap,
        "path": path,
        "dataMap": dataMap,
        "lockMap": {},
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compile simplified workflow to detailed fixed workflow JSON."
    )
    parser.add_argument(
        "--workflow",
        type=Path,
        required=True,
        help="Path to simplified workflow JSON file",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        required=True,
        help="Path to CSV file containing experiment parameters",
    )
    parser.add_argument(
        "--out", type=Path, required=True, help="Output path for compiled JSON"
    )
    args = parser.parse_args()

    with open(args.workflow, "r", encoding="utf-8") as f:
        workflow = json.load(f)
    compiled = compile_to_fixed(workflow, args.csv)
    args.out.write_text(
        json.dumps(compiled, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Compiled workflow saved to {args.out}")


if __name__ == "__main__":
    main()
