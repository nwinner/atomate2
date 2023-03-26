from datetime import datetime
from typing import Callable, ClassVar, Dict, List, Mapping, Set, Tuple, Type, TypeVar

import numpy as np
from monty.json import MontyDecoder
from monty.tempfile import ScratchDir
from pydantic import BaseModel, Field
from pymatgen.analysis.defects.core import Adsorbate, Defect
from pymatgen.analysis.defects.corrections.freysoldt import (
    get_freysoldt2d_correction,
    get_freysoldt_correction,
)
from pymatgen.analysis.defects.finder import DefectSiteFinder
from pymatgen.analysis.defects.thermo import DefectEntry, MultiFormationEnergyDiagram
from pymatgen.analysis.phase_diagram import PhaseDiagram
from pymatgen.core import Element
from pymatgen.entries.computed_entries import ComputedEntry, ComputedStructureEntry
from pymatgen.io.cp2k.utils import get_truncated_coulomb_cutoff
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

from atomate2 import SETTINGS
from atomate2.common.schemas.structure import StructureMetadata
from atomate2.cp2k.schemas.calc_types.enums import RunType
from atomate2.cp2k.schemas.task import Cp2kObject, TaskDocument

__all__ = ["DefectDoc"]

T = TypeVar("T", bound="DefectDoc")
S = TypeVar("S", bound="DefectiveMaterialDoc")
V = TypeVar("V", bound="DefectValidation")


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
    defect_ids: Mapping[RunType, str] = Field(
        None, description="Map run types of defect entry to task id"
    )
    bulk_ids: Mapping[RunType, str] = Field(
        None, description="Map run types of bulk entry to task id"
    )
    task_ids: List[str] = Field(
        None, description="All defect task ids used in creating this defect doc."
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
    metadata: Dict = Field(None, description="Metadata for this defect")
    valid: Mapping[RunType, Dict] = Field(
        None, description="Whether each run type has a valid entry"
    )

    def update_one(
        self, defect_task, bulk_task, dielectric, query="defect", key="task_id"
    ):

        # Metadata
        self.last_updated = datetime.now()
        self.created_at = datetime.now()

        defect = self.get_defect_from_task(query=query, task=defect_task)
        d_id = defect_task[key]
        b_id = bulk_task[key]
        defect_task = TaskDocument(**defect_task["output"])
        bulk_task = TaskDocument(**bulk_task["output"])  # TODO Atomate2Store
        defect_entry, valid = self.get_defect_entry_from_tasks(
            defect_task, bulk_task, defect, dielectric
        )
        bulk_entry = self.get_bulk_entry_from_task(bulk_task)

        rt = defect_task.calcs_reversed[0].run_type
        defect_task.calcs_reversed[0].task_type
        defect_task.calcs_reversed[0].calc_type
        current_largest_sc = (
            self.defect_entries[rt].sc_entry.composition.num_atoms
            if rt in self.defect_entries
            else 0
        )
        potential_largest_sc = defect_entry.sc_entry.composition.num_atoms
        if potential_largest_sc > current_largest_sc or (
            potential_largest_sc == current_largest_sc
            and defect_entry.sc_entry.energy < self.defect_entries[rt].sc_entry.energy
        ):
            self.defect_entries[rt] = defect_entry
            self.defect_ids[rt] = d_id
            self.bulk_entries[rt] = bulk_entry
            self.bulk_ids[rt] = b_id
            self.vbm[rt] = bulk_task.output.vbm
            self.valid[rt] = valid

        self.task_ids = list(set(self.task_ids) | {d_id})

    def update_many(
        self, defect_tasks: List, bulk_tasks: List, dielectrics: List, query="defect"
    ):
        for defect_task, bulk_task, dielectric in zip(
            defect_tasks, bulk_tasks, dielectrics
        ):
            self.update_one(
                defect_task=defect_task,
                bulk_task=bulk_task,
                dielectric=dielectric,
                query=query,
            )

    @classmethod
    def from_tasks(
        cls: Type[T],
        defect_task,
        bulk_task,
        dielectric,
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
        defect_task_id = defect_task[key]
        defect = cls.get_defect_from_task(query=query, task=defect_task)
        defect_task = TaskDocument(**defect_task["output"])
        bulk_task_id = bulk_task[key]
        bulk_task = TaskDocument(**bulk_task["output"])

        # Metadata
        last_updated = datetime.now()
        created_at = datetime.now()

        rt = defect_task.calcs_reversed[0].run_type

        metadata = {}
        defect_entry, valid = cls.get_defect_entry_from_tasks(
            defect_task, bulk_task, defect, dielectric
        )
        valid = {rt: valid}
        defect_entries = {rt: defect_entry}
        bulk_entries = {rt: cls.get_bulk_entry_from_task(bulk_task)}
        vbm = {rt: bulk_task.output.vbm}

        metadata["defect_origin"] = (
            "intrinsic"
            if all(
                el in defect_entries[rt].defect.structure.composition
                for el in defect_entries[rt].defect.element_changes
            )
            else "extrinsic"
        )

        data = {
            "defect_entries": defect_entries,
            "bulk_entries": bulk_entries,
            "defect_ids": {rt: defect_task_id},
            "bulk_ids": {rt: bulk_task_id},
            "last_updated": last_updated,
            "created_at": created_at,
            "task_ids": [defect_task_id],
            "material_id": material_id,
            "defect": defect_entries[rt].defect,
            "charge": defect_entries[rt].charge_state,
            "name": defect_entries[rt].defect.name,
            "vbm": vbm,
            "metadata": metadata,
            "valid": valid,
        }
        prim = SpacegroupAnalyzer(
            defect_entries[rt].defect.structure
        ).get_primitive_standard_structure()
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
            dielectric: Dielectric doc if the defect is charged. If not present, no
                dielectric corrections will be performed, even if the defect is charged.
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
        parameters["defect"] = defect
        valid = DefectValidation().process_entry(parameters)
        return defect_entry, valid

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
            corr, met = getattr(cls, correction)(parameters)
            corrections.update(corr)
            metadata.update(met)
        return corrections, metadata

    @classmethod
    def get_freysoldt_correction(cls, parameters) -> Tuple[Dict, Dict]:
        if parameters["charge_state"] and not parameters.get("2d"):
            result = get_freysoldt_correction(
                q=parameters["charge_state"],
                dielectric=np.array(
                    parameters["dielectric"]
                ),  # TODO pmg-analysis expects np array here
                defect_locpot=parameters["defect_v_hartree"],
                bulk_locpot=parameters["bulk_v_hartree"],
                defect_frac_coords=parameters["defect_frac_sc_coords"],
            )
            return {"freysoldt": result.correction_energy}, result.metadata
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

                # TODO builder ensure structures are commensurate, but the
                # sxdefectalign2d requires exact match between structures
                # (to about 6 digits of precision). No good solution right now,
                # Just setting def lattice with bulk lattice, which will shift
                # the locpot data
                parameters["defect_v_hartree"].structure.lattice = parameters[
                    "bulk_v_hartree"
                ].structure.lattice

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

                result = get_freysoldt2d_correction(
                    q=parameters["charge_state"],
                    dielectric=dielectric,
                    defect_locpot=ldef,
                    bulk_locpot=lref,
                    defect_frac_coords=parameters["defect_frac_sc_coords"],
                    energy_cutoff=520,
                    slab_buffer=2,
                )
                return {"freysoldt": result.correction_energy}, result.metadata
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
        Get parameters necessary to create a defect entry from defect and bulk
        task dicts
        Args:
            defect_task: task dict for the defect calculation
            bulk_task: task dict for the bulk calculation.
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
            "initial_defect_structure": defect_task.input.structure,
            "final_defect_structure": final_defect_structure,
            "charge_state": defect_task.output.structure.charge,
            "defect_frac_sc_coords": defect_frac_sc_coords,
            "defect_v_hartree": MontyDecoder().process_decoded(
                defect_task.cp2k_objects[Cp2kObject.v_hartree]  # type: ignore
            ),  # TODO CP2K spec name
            "bulk_v_hartree": MontyDecoder().process_decoded(
                bulk_task.cp2k_objects[Cp2kObject.v_hartree]  # type: ignore
            ),  # TODO CP2K spec name
        }

        if defect_task.tags and "2d" in defect_task.tags:
            parameters["2d"] = True

        return parameters


class DefectValidation(BaseModel):
    """Validate a task document for defect processing."""

    MAX_ATOMIC_RELAXATION: float = Field(
        0.02,
        description="Threshold for the mean absolute displacement of atoms outside a defect's radius of isolution",
    )

    DESORPTION_DISTANCE: float = Field(
        3, description="Distance to consider adsorbate as desorbed"
    )

    def process_entry(self, parameters) -> Dict:
        """
        Gets a dictionary of {validator: result}. Result true for passing,
        false for failing.
        """
        v = {}
        v.update(self._atomic_relaxation(parameters))
        v.update(self._desorption(parameters))
        return v

    def _atomic_relaxation(self, parameters):
        """
        Returns false if the mean displacement outside the isolation radius is greater
        than the cutoff.
        """
        in_struc = parameters["initial_defect_structure"]
        out_struc = parameters["final_defect_structure"]
        sites = out_struc.get_sites_in_sphere(
            parameters["defect_frac_sc_coords"],
            get_truncated_coulomb_cutoff(in_struc),
            include_index=True,
        )
        inside_sphere = [site.index for site in sites]
        outside_sphere = [i for i in range(len(out_struc)) if i not in inside_sphere]
        distances = np.array(
            [site.distance(in_struc[i]) for i, site in enumerate(out_struc)]
        )
        distances_outside = distances[outside_sphere]
        if np.mean(distances_outside) > self.MAX_ATOMIC_RELAXATION:
            return {"atomic_relaxation": False}
        return {"atomic_relaxation": True}

    def _desorption(self, parameters):
        """Returns false if any atom is too far from all other atoms."""
        if isinstance(parameters["defect"], Adsorbate):
            out_struc = parameters["final_defect_structure"]
            defect_site = out_struc.get_sites_in_sphere(
                out_struc.lattice.get_cartesian_coords(
                    parameters["defect_frac_sc_coords"]
                ),
                0.1,
                include_index=True,
            )[0]
            distances = [
                defect_site.distance(site)
                for i, site in enumerate(out_struc)
                if i != defect_site.index
            ]
            if all(d > self.DESORPTION_DISTANCE for d in distances):
                return {"desorption": False}
        return {"desorption": True}


class DefectiveMaterialDoc(StructureMetadata):
    """Document containing all / many defect tasks for a single material ID."""

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
        els = {Element(e) for e in self.defect_docs[0].defect.structure.symbol_set}
        for d in self.defect_docs:
            els = els | set(d.defect.element_changes.keys())
        return els

    def get_formation_energy_diagram(
        self,
        run_type: RunType | str,
        atomic_entries: List[ComputedEntry],
        phase_diagram: PhaseDiagram,
        filters: List[Callable] | None = None,
    ) -> MultiFormationEnergyDiagram:

        filters = filters if filters else [lambda _: True]
        els: Set[Element] = set()
        defect_entries = []
        bulk_entries = []
        vbms = []
        if isinstance(run_type, str):
            run_type = RunType(run_type)
        for doc in filter(lambda x: all(f(x) for f in filters), self.defect_docs):
            if doc.defect_entries.get(run_type):
                els = els | set(doc.defect.element_changes.keys())
                defect_entries.append(doc.defect_entries.get(run_type))
                bulk_entries.append(doc.bulk_entries.get(run_type))
                vbms.append(doc.vbm.get(run_type))

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
