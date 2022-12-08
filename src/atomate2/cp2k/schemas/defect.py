from datetime import datetime
from tokenize import group
from typing import ClassVar, TypeVar, Type, Dict, Tuple, Mapping, List
from pydantic import BaseModel, Field
from pydantic import validator
from itertools import groupby

from monty.json import MontyDecoder
from monty.tempfile import ScratchDir

from pymatgen.core import Structure, Element
from pymatgen.entries.computed_entries import ComputedEntry, ComputedStructureEntry
from pymatgen.analysis.phase_diagram import PhaseDiagram
from pymatgen.analysis.defects.core import Defect, DefectType
from pymatgen.analysis.defects.corrections import (
    get_freysoldt_correction,
    get_freysoldt2d_correction,
)
from pymatgen.analysis.defects.thermo import (
    DefectEntry,
    DefectSiteFinder,
    FormationEnergyDiagram,
    MultiFormationEnergyDiagram
)
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

from emmet.core.utils import ValueEnum

from atomate2 import SETTINGS
from atomate2.common.schemas.structure import StructureMetadata
from atomate2.cp2k.schemas.calc_types.utils import run_type, task_type, calc_type
from atomate2.cp2k.schemas.calc_types.enums import CalcType, TaskType, RunType
from atomate2.cp2k.schemas.task import TaskDocument

__all__ = ["DefectDoc"]

T = TypeVar("T", bound="DefectDoc")
S = TypeVar("S", bound="DefectiveMaterialDoc")


class DefectDoc(StructureMetadata):
    """
    A document used to represent a single defect. e.g. a O vacancy with a -2 charge.
    This document can contain an arbitrary number of defect entries, originating from
    pairs (defect and bulk) of calculations. This document provides access to the "best"
    calculation of each run_type.
    """

    property_name: ClassVar[str] = "defect"

    defect: Defect = Field(
        None, description="Pymatgen defect object for this defect doc"
    )

    charge: int = Field(None, description="Charge state for this defect")

    name: str = Field(
        None, description="Name of this defect as generated by the defect object"
    )

    material_id: str = Field(
        None, description="Unique material ID for the bulk material"
    )  # TODO Change to MPID

    # TODO Should it be all (defect + bulk) ids?
    task_ids: List[str] = Field(
        None, description="All defect task ids used in creating this defect doc."
    )

    calc_types: Mapping[str, CalcType] = Field(  # type: ignore
        None,
        description="Calculation types for all the calculations that make up this material",
    )
    task_types: Mapping[str, TaskType] = Field(
        None,
        description="Task types for all the calculations that make up this material",
    )
    run_types: Mapping[str, RunType] = Field(
        None,
        description="Run types for all the calculations that make up this material",
    )

    best_tasks: Mapping[RunType, Tuple[str, str]] = Field(
        None, description="Task ids (defect task, bulk task) for all tasks of a RunType"
    )

    all_tasks: Mapping[RunType, List[Tuple[str, str]]] = Field(
        None, description="Task ids (defect task, bulk task) for all tasks of a RunType"
    )

    defect_entries: Mapping[RunType, DefectEntry] = Field(
        None, description="Dictionary for tracking entries for CP2K calculations"
    )

    bulk_entries: Mapping[RunType, ComputedStructureEntry] = Field(
        None, description="Computed structure entry for the bulk calc."
    )

    vbm: Mapping[RunType, float] = Field(
        None,
        description="VBM for bulk task of each run type. Used for aligning potential",
    )

    last_updated: datetime = Field(
        description="Timestamp for when this document was last updated",
        default_factory=datetime.utcnow,
    )

    created_at: datetime = Field(
        description="Timestamp for when this material document was first created",
        default_factory=datetime.utcnow,
    )

    metadata: Dict = Field(description="Metadata for this defect")

    def update(self, defect_task, bulk_task, dielectric, query="defect", key="task_id"):

        # Metadata
        self.last_updated = datetime.now()
        self.created_at = datetime.now()

        defect = self.get_defect_from_task(query=query, task=defect_task)
        d_id = defect_task[key]
        b_id = bulk_task[key]
        defect_task = TaskDocument(**defect_task)
        bulk_task = TaskDocument(**bulk_task)
        defect_entry = self.get_defect_entry_from_tasks(
            defect_task, bulk_task, defect, dielectric
        )
        bulk_entry = self.get_bulk_entry_from_task(bulk_task)

        rt = defect_task.calcs_reversed[0].run_type
        current_largest_sc = self.defect_entries[rt].sc_entry.composition.num_atoms
        potential_largest_sc = defect_entry.sc_entry.composition.num_atoms
        if (
            rt not in self.defect_entries
            or potential_largest_sc > current_largest_sc
            or (
                potential_largest_sc == current_largest_sc
                and defect_entry.sc_entry.energy
                < self.defect_entries[rt].sc_entry.energy
            )
        ):
            self.defect_entries[rt] = defect_entry
            self.bulk_entries[rt] = bulk_entry
            self.best_tasks[rt] = (d_id, b_id)

        self.all_tasks[rt].append((d_id, b_id))
        self.metadata["convergence"].append((current_largest_sc, defect_entry.corrected_energy - bulk_entry.energy))

    def update_all(
        self, defect_tasks: List, bulk_tasks: List, dielectrics: List, query="defect"
    ):
        for defect_task, bulk_task, dielectric in zip(
            defect_tasks, bulk_tasks, dielectrics
        ):
            self.update(
                defect_task=defect_task,
                bulk_task=bulk_task,
                dielectric=dielectric,
                query=query,
            )

    @classmethod
    def from_tasks(
        cls: Type[T],
        defect_tasks: List,
        bulk_tasks: List,
        dielectrics: List,
        query="defect",
        key="task_id",
        material_id=None,
    ) -> T:
        """
        The standard way to create this document.
        Args:
            tasks: A list of defect,bulk task pairs which will be used to construct a
                series of DefectEntry objects.
            query: How to retrieve the defect object stored in the task.
        """
        defect_task_ids = [defect_task[key] for defect_task in defect_tasks]
        bulk_task_ids = [bulk_task[key] for bulk_task in bulk_tasks]
        bulk_tasks = [TaskDocument(**bulk_task["output"]) for bulk_task in bulk_tasks]
        defects = [
            cls.get_defect_from_task(query=query, task=defect_task)
            for defect_task in defect_tasks
        ]
        defect_tasks = [
            TaskDocument(**defect_task["output"]) for defect_task in defect_tasks
        ]

        # Metadata
        last_updated = datetime.now() or max(task.last_updated for task in defect_tasks)
        created_at = datetime.now() or min(task.completed_at for task in defect_tasks)

        run_types = {
            id: task.calcs_reversed[0].run_type
            for id, task in zip(defect_task_ids, defect_tasks)
        }
        task_types = {
            id: task.calcs_reversed[0].task_type
            for id, task in zip(defect_task_ids, defect_tasks)
        }
        calc_types = {
            id: task.calcs_reversed[0].calc_type
            for id, task in zip(defect_task_ids, defect_tasks)
        }

        def _run_type(x):
            return x[0].calcs_reversed[0].run_type.value

        def _sort(x):
            # TODO return kpoint density, currently just does supercell size
            return -x[0].nsites, x[0].output.energy

        defect_entries = {}
        bulk_entries = {}
        all_tasks = {}
        best_tasks = {}
        vbm = {}
        metadata = {}
        for key, tasks_for_runtype in groupby(
            sorted(
                zip(
                    defect_tasks,
                    bulk_tasks,
                    defects,
                    dielectrics,
                    defect_task_ids,
                    bulk_task_ids,
                ),
                key=_run_type,
            ),
            key=_run_type,
        ):
            sorted_tasks = sorted(tasks_for_runtype, key=_sort)
            ents = [
                (
                    cls.get_defect_entry_from_tasks(
                        defect_task, bulk_task, defect, dielectric
                    ),
                    cls.get_bulk_entry_from_task(bulk_task),
                )
                for defect_task, bulk_task, defect, dielectric, did, bid in sorted_tasks
            ]
            rt = run_types[sorted_tasks[0][-2]]
            vbm[rt] = sorted_tasks[0][1].output.vbm
            best_tasks[rt] = (sorted_tasks[0][-2], sorted_tasks[0][-1])
            all_tasks[rt] = [(s[-2], s[-1]) for s in sorted_tasks]
            defect_entries[rt], bulk_entries[rt] = ents[0]
            metadata[key] = {
                "convergence": [
                    (
                        sorted_tasks[i][0].nsites,
                        defect_entries[rt].corrected_energy - bulk_entries[rt].energy,
                    )
                    for i in range(len(ents))
                ]
            }

        v = next(iter(defect_entries.values()))
        metadata["defect_origin"] = (
            "intrinsic"
            if all(
                el in v.defect.structure.composition
                for el in v.defect.element_changes.keys()
            )
            else "extrinsic"
        )

        data = {
            "defect_entries": defect_entries,
            "bulk_entries": bulk_entries,
            "run_types": run_types,
            "task_types": task_types,
            "calc_types": calc_types,
            "last_updated": last_updated,
            "created_at": created_at,
            "task_ids": defect_task_ids,
            "all_tasks": all_tasks,
            "best_tasks": best_tasks,
            "material_id": material_id if material_id else v.parameters["material_id"],
            "defect": v.defect,
            "charge": v.charge_state,
            "name": v.defect.name,
            "vbm": vbm,
            "metadata": metadata,
        }
        prim = SpacegroupAnalyzer(v.defect.structure).get_primitive_standard_structure()
        data.update(StructureMetadata.from_structure(prim).dict())
        return cls(**data)

    @classmethod
    def get_defect_entry_from_tasks(
        cls,
        defect_task: TaskDocument,
        bulk_task: TaskDocument,
        defect: Defect,
        dielectric=None,
    ):
        """
        Extract a defect entry from a single pair (defect and bulk) of tasks.

        Args:
            defect_task: task dict for the defect calculation
            bulk_task: task dict for the bulk calculation
            dielectric: Dielectric doc if the defect is charged. If not present, no dielectric
                corrections will be performed, even if the defect is charged.
            query: Mongo-style query to retrieve the defect object from the defect task
        """
        parameters = cls.get_parameters_from_tasks(
            defect_task=defect_task, bulk_task=bulk_task
        )
        if dielectric:
            parameters["dielectric"] = dielectric

        corrections, metadata = cls.get_correction_from_parameters(parameters)

        sc_entry = ComputedStructureEntry(
            structure=parameters["final_defect_structure"],
            energy=parameters["defect_energy"],
        )

        defect_entry = DefectEntry(
            defect=defect,
            charge_state=parameters["charge_state"],
            sc_entry=sc_entry,
            sc_defect_frac_coords=parameters["defect_frac_sc_coords"],
            corrections=corrections,
        )

        return defect_entry

    @classmethod
    def get_bulk_entry_from_task(cls, bulk_task: TaskDocument):
        return ComputedStructureEntry(
            structure=bulk_task.structure,
            energy=bulk_task.output.energy,
        )

    @classmethod
    def get_correction_from_parameters(cls, parameters) -> Tuple[Dict, Dict]:
        corrections = {}
        metadata = {}
        for correction in ["get_freysoldt_correction", "get_freysoldt2d_correction"]:
            c, m = getattr(cls, correction)(parameters)
            corrections.update(c)
            metadata.update(m)
        return corrections, metadata

    @classmethod
    def get_freysoldt_correction(cls, parameters) -> Tuple[Dict, Dict]:
        if parameters["charge_state"] and not parameters.get("2d"):
            return get_freysoldt_correction(
                q=parameters["charge_state"],
                dielectric=parameters["dielectric"],
                defect_locpot=parameters["defect_v_hartree"],
                bulk_locpot=parameters["bulk_v_hartree"],
                defect_frac_coords=parameters["defect_frac_sc_coords"],
            )
        return {}, {}

    @classmethod
    def get_freysoldt2d_correction(cls, parameters):

        from pymatgen.io.vasp.outputs import VolumetricData as VaspVolumetricData

        if parameters["charge_state"] and parameters.get("2d"):
            eps_parallel = (
                parameters["dielectric"][0][0] + parameters["dielectric"][1][1]
            ) / 2
            eps_perp = parameters["dielectric"][2][2]
            dielectric = (eps_parallel - 1) / (1 - 1 / eps_perp)
            with ScratchDir("."):

                lref = VaspVolumetricData(
                    structure=parameters["bulk_v_hartree"].structure,
                    data=parameters["bulk_v_hartree"].data,
                )
                ldef = VaspVolumetricData(
                    structure=parameters["defect_v_hartree"].structure,
                    data=parameters["defect_v_hartree"].data,
                )
                lref.write_file("LOCPOT.ref")
                ldef.write_file("LOCPOT.def")

                return get_freysoldt2d_correction(
                    q=parameters["charge_state"],
                    dielectric=dielectric,
                    defect_locpot=ldef,
                    bulk_locpot=lref,
                    defect_frac_coords=parameters["defect_frac_sc_coords"],
                    energy_cutoff=520,
                    slab_buffer=2,
                )
        return {}, {}

    @classmethod
    def get_defect_from_task(cls, query, task):
        """
        Unpack a Mongo-style query and retrieve a defect object from a task.
        """
        defect = unpack(query.split("."), task)
        return MontyDecoder().process_decoded(defect)

    @classmethod
    def get_parameters_from_tasks(
        cls, defect_task: TaskDocument, bulk_task: TaskDocument
    ):
        """
        Get parameters necessary to create a defect entry from defect and bulk task dicts
        Args:
            defect_task: task dict for the defect calculation
            bulk_task: task dict for the bulk calculation
        """

        final_defect_structure = defect_task.structure
        final_bulk_structure = bulk_task.structure

        ghost = [
            index
            for index, prop in enumerate(
                final_defect_structure.site_properties.get("ghost")
            )
            if prop
        ]
        if ghost:
            defect_frac_sc_coords = final_defect_structure[ghost[0]].frac_coords
        else:
            defect_frac_sc_coords = DefectSiteFinder(SETTINGS.SYMPREC).get_defect_fpos(
                defect_structure=final_defect_structure,
                base_structure=final_bulk_structure,
            )
        parameters = {
            "defect_energy": defect_task.output.energy,
            "bulk_energy": bulk_task.output.energy,
            "final_defect_structure": final_defect_structure,
            "charge_state": defect_task.output.structure.charge,
            "defect_frac_sc_coords": defect_frac_sc_coords,
            "defect_v_hartree": MontyDecoder().process_decoded(
                defect_task.cp2k_objects["v_hartree"]
            ),  # TODO CP2K spec name
            "bulk_v_hartree": MontyDecoder().process_decoded(
                bulk_task.cp2k_objects["v_hartree"]
            ),  # TODO CP2K spec name
        }

        if defect_task.tags and "2d" in defect_task.tags:
            parameters["2d"] = True

        return parameters


class DefectiveMaterialDoc(StructureMetadata):
    """Document containing all / many defect tasks for a single material ID"""

    property_name: ClassVar[str] = "defective material"

    material_id: str = Field(
        None, description="Unique material ID for the bulk material"
    )  # TODO Change to MPID

    defect_docs: List[DefectDoc] = Field(None, description="Defect Docs")

    last_updated: datetime = Field(
        description="Timestamp for when this document was last updated",
        default_factory=datetime.utcnow,
    )

    created_at: datetime = Field(
        description="Timestamp for when this material document was first created",
        default_factory=datetime.utcnow,
    )

    metadata: Dict = Field(None, description="Metadata for this object")

    @classmethod
    def from_docs(cls: Type["S"], defect_docs: DefectDoc, material_id: str) -> S:
        return cls(
            defect_docs=defect_docs,
            material_id=material_id,
            last_updated=max(d.last_updated for d in defect_docs),
            created_at=datetime.now(),
        )

    @property
    def element_set(self) -> set:
        els = set(Element(e) for e in self.defect_docs[0].defect.structure.symbol_set)
        for d in self.defect_docs:
            els = els | set(d.defect.element_changes.keys())
        return els

    def get_formation_energy_diagram(
        self,
        run_type: RunType | str,
        atomic_entries: List[ComputedEntry],
        phase_diagram: PhaseDiagram,
        filters: Dict | None = None,
    ) -> MultiFormationEnergyDiagram:

        filters = filters if filters else {}

        els = set()
        defect_entries = []
        bulk_entries = []
        vbms = []
        for doc in self.defect_docs:
            els = els | set(doc.defect.element_changes.keys())
            defect_entries.append(doc.defect_entries.get(run_type))
            bulk_entries.append(doc.bulk_entries.get(run_type))
            vbms.append(doc.vbm.get(run_type))

        # TODO bulks and vbms
        # form en diagram takes one bulk entry and one bulk vbm
        # These, however, can be different for each defect/bulk task pair
        # Need to convert the differences into energy adjustments so that
        # form en diagram is consistent with all of them

        return MultiFormationEnergyDiagram.with_atomic_entries(
            bulk_entry=bulk_entries[0],
            defect_entries=defect_entries,
            atomic_entries=atomic_entries,
            phase_diagram=phase_diagram,
            vbm=vbms[0],
        )

def unpack(query, d):
    if not query:
        return d
    if isinstance(d, List):
        return unpack(query[1:], d.__getitem__(int(query.pop(0))))
    return unpack(query[1:], d.__getitem__(query.pop(0)))
