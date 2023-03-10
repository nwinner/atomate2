"""Module to define various calculation types as Enums for CP2K."""
from itertools import product
from pathlib import Path

from monty.serialization import loadfn

_RUN_TYPE_DATA = loadfn(str(Path(__file__).parent.joinpath("run_types.yaml").resolve()))
_TASK_TYPES = [
    "Static",
    "Structure Optimization",
    "Constrained Structure Optimization",
    "Molecular Dynamics",
    "NSCF Line",
    "NSCF Uniform",
    "Unrecognized",
]

_RUN_TYPES = []
for functional_class in _RUN_TYPE_DATA:
    for rt in _RUN_TYPE_DATA[functional_class]:
        for vdw in ["", "-RVV10", "-LMKLL", "-DRSLL", "-D3", "-D2", "-D3(BJ)"]:
            for u in ["", "+U"]:
                _RUN_TYPES.append(f"{rt}{vdw}{u}")


def get_enum_source(enum_name, doc, items):
    header = f"""
class {enum_name}(ValueEnum):
    \"\"\" {doc} \"\"\"\n
"""
    items = [f'    {const} = "{val}"' for const, val in items.items()]

    return header + "\n".join(items)


run_type_enum = get_enum_source(
    "RunType",
    "CP2K calculation run types",
    dict(
        {
            "_".join(rt.split())
            .replace("+", "_")
            .replace("-", "_")
            .replace("(", "_")
            .replace(")", ""): rt
            for rt in _RUN_TYPES
        }
    ),
)
task_type_enum = get_enum_source(
    "TaskType",
    "CP2K calculation task types",
    {"_".join(tt.split()): tt for tt in _TASK_TYPES},
)


def get_calc_type_key(rt):
    """Conveniece function for readability."""
    s = "_".join(rt.split())
    s = s.replace("+", "_").replace("-", "_").replace("(", "_").replace(")", "")
    return f"{s}"


calc_type_enum = get_enum_source(
    "CalcType",
    "CP2K calculation types",
    {
        f"{get_calc_type_key(rt)}_{'_'.join(tt.split())}": f"{rt} {tt}"
        for rt, tt in product(_RUN_TYPES, _TASK_TYPES)
    },
)


with open(Path(__file__).parent / "enums.py", "w") as f:
    f.write(
        """\"\"\"
Autogenerated Enums for CP2K RunType, TaskType, and CalcType
Do not edit this by hand. Edit generate.py or run_types.yaml instead
\"\"\"
from emmet.core.utils import ValueEnum

"""
    )
    f.write(run_type_enum)
    f.write("\n\n")
    f.write(task_type_enum)
    f.write("\n\n")
    f.write(calc_type_enum)
    f.write("\n")
