"""Core jobs for running VASP calculations."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from custodian.vasp.handlers import (
    FrozenJobErrorHandler,
    IncorrectSmearingHandler,
    LargeSigmaHandler,
    MeshSymmetryErrorHandler,
    PositiveEnergyErrorHandler,
    StdErrHandler,
    VaspErrorHandler,
)
from pymatgen.alchemy.materials import TransformedStructure
from pymatgen.alchemy.transmuters import StandardTransmuter
from pymatgen.core.structure import Structure

from atomate2.common.utils import get_transformations
from atomate2.vasp.jobs.base import BaseVaspMaker, vasp_job
from atomate2.vasp.sets.base import VaspInputGenerator
from atomate2.vasp.sets.core import (
    HSEBSSetGenerator,
    HSERelaxSetGenerator,
    HSEStaticSetGenerator,
    HSETightRelaxSetGenerator,
    MDSetGenerator,
    NonSCFSetGenerator,
    RelaxSetGenerator,
    StaticSetGenerator,
    TightRelaxSetGenerator,
)

logger = logging.getLogger(__name__)

__all__ = [
    "StaticMaker",
    "RelaxMaker",
    "NonSCFMaker",
    "DielectricMaker",
    "HSEBSMaker",
    "HSERelaxMaker",
    "HSEStaticMaker",
    "TightRelaxMaker",
    "HSETightRelaxMaker",
    "TransmuterMaker",
    "MDMaker",
]


@dataclass
class StaticMaker(BaseVaspMaker):
    """
    Maker to create VASP static jobs.

    Parameters
    ----------
    name : str
        The job name.
    input_set_generator : .VaspInputGenerator
        A generator used to make the input set.
    write_input_set_kwargs : dict
        Keyword arguments that will get passed to :obj:`.write_vasp_input_set`.
    copy_vasp_kwargs : dict
        Keyword arguments that will get passed to :obj:`.copy_vasp_outputs`.
    run_vasp_kwargs : dict
        Keyword arguments that will get passed to :obj:`.run_vasp`.
    task_document_kwargs : dict
        Keyword arguments that will get passed to :obj:`.TaskDocument.from_directory`.
    stop_children_kwargs : dict
        Keyword arguments that will get passed to :obj:`.should_stop_children`.
    write_additional_data : dict
        Additional data to write to the current directory. Given as a dict of
        {filename: data}. Note that if using FireWorks, dictionary keys cannot contain
        the "." character which is typically used to denote file extensions. To avoid
        this, use the ":" character, which will automatically be converted to ".". E.g.
        ``{"my_file:txt": "contents of the file"}``.
    """

    name: str = "static"
    input_set_generator: VaspInputGenerator = field(default_factory=StaticSetGenerator)


@dataclass
class RelaxMaker(BaseVaspMaker):
    """
    Maker to create VASP relaxation jobs.

    Parameters
    ----------
    name : str
        The job name.
    input_set_generator : .VaspInputGenerator
        A generator used to make the input set.
    write_input_set_kwargs : dict
        Keyword arguments that will get passed to :obj:`.write_vasp_input_set`.
    copy_vasp_kwargs : dict
        Keyword arguments that will get passed to :obj:`.copy_vasp_outputs`.
    run_vasp_kwargs : dict
        Keyword arguments that will get passed to :obj:`.run_vasp`.
    task_document_kwargs : dict
        Keyword arguments that will get passed to :obj:`.TaskDocument.from_directory`.
    stop_children_kwargs : dict
        Keyword arguments that will get passed to :obj:`.should_stop_children`.
    write_additional_data : dict
        Additional data to write to the current directory. Given as a dict of
        {filename: data}. Note that if using FireWorks, dictionary keys cannot contain
        the "." character which is typically used to denote file extensions. To avoid
        this, use the ":" character, which will automatically be converted to ".". E.g.
        ``{"my_file:txt": "contents of the file"}``.
    """

    name: str = "relax"
    input_set_generator: VaspInputGenerator = field(default_factory=RelaxSetGenerator)


@dataclass
class TightRelaxMaker(BaseVaspMaker):
    """
    Maker to create tight VASP relaxation jobs.

    Parameters
    ----------
    name : str
        The job name.
    input_set_generator : .VaspInputGenerator
        A generator used to make the input set.
    write_input_set_kwargs : dict
        Keyword arguments that will get passed to :obj:`.write_vasp_input_set`.
    copy_vasp_kwargs : dict
        Keyword arguments that will get passed to :obj:`.copy_vasp_outputs`.
    run_vasp_kwargs : dict
        Keyword arguments that will get passed to :obj:`.run_vasp`.
    task_document_kwargs : dict
        Keyword arguments that will get passed to :obj:`.TaskDocument.from_directory`.
    stop_children_kwargs : dict
        Keyword arguments that will get passed to :obj:`.should_stop_children`.
    write_additional_data : dict
        Additional data to write to the current directory. Given as a dict of
        {filename: data}. Note that if using FireWorks, dictionary keys cannot contain
        the "." character which is typically used to denote file extensions. To avoid
        this, use the ":" character, which will automatically be converted to ".". E.g.
        ``{"my_file:txt": "contents of the file"}``.
    """

    name: str = "tight relax"
    input_set_generator: VaspInputGenerator = field(
        default_factory=TightRelaxSetGenerator
    )


@dataclass
class NonSCFMaker(BaseVaspMaker):
    """
    Maker to create non self consistent field VASP jobs.

    Parameters
    ----------
    name : str
        The job name.
    input_set_generator : .VaspInputGenerator
        A generator used to make the input set.
    write_input_set_kwargs : dict
        Keyword arguments that will get passed to :obj:`.write_vasp_input_set`.
    copy_vasp_kwargs : dict
        Keyword arguments that will get passed to :obj:`.copy_vasp_outputs`.
    run_vasp_kwargs : dict
        Keyword arguments that will get passed to :obj:`.run_vasp`.
    task_document_kwargs : dict
        Keyword arguments that will get passed to :obj:`.TaskDocument.from_directory`.
    stop_children_kwargs : dict
        Keyword arguments that will get passed to :obj:`.should_stop_children`.
    write_additional_data : dict
        Additional data to write to the current directory. Given as a dict of
        {filename: data}. Note that if using FireWorks, dictionary keys cannot contain
        the "." character which is typically used to denote file extensions. To avoid
        this, use the ":" character, which will automatically be converted to ".". E.g.
        ``{"my_file:txt": "contents of the file"}``.
    """

    name: str = "non-scf"
    input_set_generator: VaspInputGenerator = field(default_factory=NonSCFSetGenerator)

    @vasp_job
    def make(
        self,
        structure: Structure,
        prev_vasp_dir: str | Path | None,
        mode: str = "uniform",
    ):
        """
        Run a non-scf VASP job.

        Parameters
        ----------
        structure : .Structure
            A pymatgen structure object.
        prev_vasp_dir : str or Path or None
            A previous VASP calculation directory to copy output files from.
        mode : str
            Type of band structure calculation. Options are:
            - "line": Full band structure along symmetry lines.
            - "uniform": Uniform mesh band structure.
        """
        self.input_set_generator.mode = mode

        if "parse_dos" not in self.task_document_kwargs:
            # parse DOS only for uniform band structure
            self.task_document_kwargs["parse_dos"] = mode == "uniform"

        if "parse_bandstructure" not in self.task_document_kwargs:
            self.task_document_kwargs["parse_bandstructure"] = mode

        # copy previous inputs
        if "additional_vasp_files" not in self.copy_vasp_kwargs:
            self.copy_vasp_kwargs["additional_vasp_files"] = ("CHGCAR",)

        return super().make.original(self, structure, prev_vasp_dir)


@dataclass
class HSERelaxMaker(BaseVaspMaker):
    """
    Maker to create HSE06 relaxation jobs.

    Parameters
    ----------
    name : str
        The job name.
    input_set_generator : .VaspInputGenerator
        A generator used to make the input set.
    write_input_set_kwargs : dict
        Keyword arguments that will get passed to :obj:`.write_vasp_input_set`.
    copy_vasp_kwargs : dict
        Keyword arguments that will get passed to :obj:`.copy_vasp_outputs`.
    run_vasp_kwargs : dict
        Keyword arguments that will get passed to :obj:`.run_vasp`.
    task_document_kwargs : dict
        Keyword arguments that will get passed to :obj:`.TaskDocument.from_directory`.
    stop_children_kwargs : dict
        Keyword arguments that will get passed to :obj:`.should_stop_children`.
    write_additional_data : dict
        Additional data to write to the current directory. Given as a dict of
        {filename: data}. Note that if using FireWorks, dictionary keys cannot contain
        the "." character which is typically used to denote file extensions. To avoid
        this, use the ":" character, which will automatically be converted to ".". E.g.
        ``{"my_file:txt": "contents of the file"}``.
    """

    name: str = "hse relax"
    input_set_generator: VaspInputGenerator = field(
        default_factory=HSERelaxSetGenerator
    )


@dataclass
class HSETightRelaxMaker(BaseVaspMaker):
    """
    Maker to create tight VASP relaxation jobs.

    Parameters
    ----------
    name : str
        The job name.
    input_set_generator
        A generator used to make the input set.
    write_input_set_kwargs
        Keyword arguments that will get passed to :obj:`.write_vasp_input_set`.
    run_vasp_kwargs
        Keyword arguments that will get passed to :obj:`.run_vasp`.
    task_document_kwargs
        Keyword arguments that will get passed to :obj:`.TaskDocument.from_directory`.
    stop_children_kwargs
        Keyword arguments that will get passed to :obj:`.should_stop_children`.
    write_additional_data : dict
        Additional data to write to the current directory. Given as a dict of
        {filename: data}. Note that if using FireWorks, dictionary keys cannot contain
        the "." character which is typically used to denote file extensions. To avoid
        this, use the ":" character, which will automatically be converted to ".". E.g.
        ``{"my_file:txt": "contents of the file"}``.
    """

    name: str = "hse tight relax"
    input_set_generator: VaspInputGenerator = field(
        default_factory=HSETightRelaxSetGenerator
    )


@dataclass
class HSEStaticMaker(BaseVaspMaker):
    """
    Maker to create HSE06 static jobs.

    Parameters
    ----------
    name : str
        The job name.
    input_set_generator : .VaspInputGenerator
        A generator used to make the input set.
    write_input_set_kwargs : dict
        Keyword arguments that will get passed to :obj:`.write_vasp_input_set`.
    copy_vasp_kwargs : dict
        Keyword arguments that will get passed to :obj:`.copy_vasp_outputs`.
    run_vasp_kwargs : dict
        Keyword arguments that will get passed to :obj:`.run_vasp`.
    task_document_kwargs : dict
        Keyword arguments that will get passed to :obj:`.TaskDocument.from_directory`.
    stop_children_kwargs : dict
        Keyword arguments that will get passed to :obj:`.should_stop_children`.
    write_additional_data : dict
        Additional data to write to the current directory. Given as a dict of
        {filename: data}. Note that if using FireWorks, dictionary keys cannot contain
        the "." character which is typically used to denote file extensions. To avoid
        this, use the ":" character, which will automatically be converted to ".". E.g.
        ``{"my_file:txt": "contents of the file"}``.
    """

    name: str = "hse static"
    input_set_generator: VaspInputGenerator = field(
        default_factory=HSEStaticSetGenerator
    )


@dataclass
class HSEBSMaker(BaseVaspMaker):
    """
    Maker to create HSE06 band structure jobs.

    .. warning::
        The number of bands will automatically be adjusted based on the number of bands
        in the previous calculation. Therefore, if starting from a previous structure
        ensure you are starting from a static/relaxation calculation that has the same
        number of atoms (i.e., not a smaller/larger cell), as otherwise the number of
        bands may be set incorrectly.

    Parameters
    ----------
    name : str
        The job name.
    input_set_generator : .VaspInputGenerator
        A generator used to make the input set.
    write_input_set_kwargs : dict
        Keyword arguments that will get passed to :obj:`.write_vasp_input_set`.
    copy_vasp_kwargs : dict
        Keyword arguments that will get passed to :obj:`.copy_vasp_outputs`.
    run_vasp_kwargs : dict
        Keyword arguments that will get passed to :obj:`.run_vasp`.
    task_document_kwargs : dict
        Keyword arguments that will get passed to :obj:`.TaskDocument.from_directory`.
    stop_children_kwargs : dict
        Keyword arguments that will get passed to :obj:`.should_stop_children`.
    write_additional_data : dict
        Additional data to write to the current directory. Given as a dict of
        {filename: data}. Note that if using FireWorks, dictionary keys cannot contain
        the "." character which is typically used to denote file extensions. To avoid
        this, use the ":" character, which will automatically be converted to ".". E.g.
        ``{"my_file:txt": "contents of the file"}``.
    """

    name: str = "hse band structure"
    input_set_generator: VaspInputGenerator = field(default_factory=HSEBSSetGenerator)

    @vasp_job
    def make(
        self,
        structure: Structure,
        prev_vasp_dir: str | Path | None = None,
        mode="uniform",
    ):
        """
        Run a HSE06 band structure VASP job.

        Parameters
        ----------
        structure : .Structure
            A pymatgen structure object.
        prev_vasp_dir : str or Path or None
            A previous VASP calculation directory to copy output files from.
        mode : str
            Type of band structure calculation. Options are:
            - "line": Full band structure along symmetry lines.
            - "uniform": Uniform mesh band structure.
            - "gap": Get the energy at the CBM and VBM.
        """
        self.input_set_generator.mode = mode

        if mode == "gap" and prev_vasp_dir is None:
            logger.warning(
                "HSE band structure in 'gap' mode requires a previous VASP calculation "
                "directory from which to extract the VBM and CBM k-points. This "
                "calculation will instead be a standard uniform calculation."
            )
            mode = "uniform"

        if "parse_dos" not in self.task_document_kwargs:
            # parse DOS only for uniform band structure
            self.task_document_kwargs["parse_dos"] = "uniform" in mode

        if "parse_bandstructure" not in self.task_document_kwargs:
            parse_bandstructure = "uniform" if mode == "gap" else mode
            self.task_document_kwargs["parse_bandstructure"] = parse_bandstructure

        # copy previous inputs
        if (
            prev_vasp_dir is not None
            and "additional_vasp_files" not in self.copy_vasp_kwargs
        ):
            self.copy_vasp_kwargs["additional_vasp_files"] = ("CHGCAR",)

        return super().make.original(self, structure, prev_vasp_dir)


@dataclass
class DielectricMaker(BaseVaspMaker):
    """
    Maker to create dielectric calculation VASP jobs.

    .. Note::
        The input structure should be well relaxed to avoid imaginary modes. For
        example, using :obj:`TightRelaxMaker`.

    .. Note::
        If starting from a previous calculation, magnetism will be disabled if all
        MAGMOMs are less than 0.02.

    Parameters
    ----------
    name : str
        The job name.
    input_set_generator : .StaticSetGenerator
        A generator used to make the input set.
    write_input_set_kwargs : dict
        Keyword arguments that will get passed to :obj:`.write_vasp_input_set`.
    copy_vasp_kwargs : dict
        Keyword arguments that will get passed to :obj:`.copy_vasp_outputs`.
    run_vasp_kwargs : dict
        Keyword arguments that will get passed to :obj:`.run_vasp`.
    task_document_kwargs : dict
        Keyword arguments that will get passed to :obj:`.TaskDocument.from_directory`.
    stop_children_kwargs : dict
        Keyword arguments that will get passed to :obj:`.should_stop_children`.
    write_additional_data : dict
        Additional data to write to the current directory. Given as a dict of
        {filename: data}. Note that if using FireWorks, dictionary keys cannot contain
        the "." character which is typically used to denote file extensions. To avoid
        this, use the ":" character, which will automatically be converted to ".". E.g.
        ``{"my_file:txt": "contents of the file"}``.
    """

    name: str = "dielectric"
    input_set_generator: StaticSetGenerator = field(
        default_factory=lambda: StaticSetGenerator(lepsilon=True, auto_ispin=True)
    )


@dataclass
class TransmuterMaker(BaseVaspMaker):
    """
    A maker to apply transformations to a structure before writing the input sets.

    Note that if a transformation yields many structures, only the last structure in the
    list is used.

    Parameters
    ----------
    name : str
        The job name.
    transformations : tuple of str
        The transformations to apply. Given as a list of names of transformation classes
        as defined in the modules in pymatgen.transformations. For example,
        ``['DeformStructureTransformation', 'SupercellTransformation']``.
    transformation_params : tuple of dict or None
        The parameters used to instantiate each transformation class. Given as a list of
        dicts.
    input_set_generator : StaticSetGenerator
        A generator used to make the input set.
    write_input_set_kwargs : dict
        Keyword arguments that will get passed to :obj:`.write_vasp_input_set`.
    copy_vasp_kwargs : dict
        Keyword arguments that will get passed to :obj:`.copy_vasp_outputs`.
    run_vasp_kwargs : dict
        Keyword arguments that will get passed to :obj:`.run_vasp`.
    task_document_kwargs : dict
        Keyword arguments that will get passed to :obj:`.TaskDocument.from_directory`.
    stop_children_kwargs : dict
        Keyword arguments that will get passed to :obj:`.should_stop_children`.
    write_additional_data : dict
        Additional data to write to the current directory. Given as a dict of
        {filename: data}. Note that if using FireWorks, dictionary keys cannot contain
        the "." character which is typically used to denote file extensions. To avoid
        this, use the ":" character, which will automatically be converted to ".". E.g.
        ``{"my_file:txt": "contents of the file"}``.
    """

    name: str = "transmuter"
    transformations: tuple[str, ...] = field(default_factory=tuple)
    transformation_params: tuple[dict, ...] | None = None
    input_set_generator: VaspInputGenerator = field(default_factory=StaticSetGenerator)

    @vasp_job
    def make(
        self,
        structure: Structure,
        prev_vasp_dir: str | Path | None = None,
    ):
        """
        Run a transmuter VASP job.

        Parameters
        ----------
        structure : Structure
            A pymatgen structure object.
        prev_vasp_dir : str or Path or None
            A previous VASP calculation directory to copy output files from.
        """
        transformations = get_transformations(
            self.transformations, self.transformation_params
        )
        ts = TransformedStructure(structure)
        transmuter = StandardTransmuter([ts], transformations)
        structure = transmuter.transformed_structures[-1].final_structure

        # to avoid mongoDB errors, ":" is automatically converted to "."
        if "transformations:json" not in self.write_additional_data:
            tjson = transmuter.transformed_structures[-1]
            self.write_additional_data["transformations:json"] = tjson

        return super().make.original(self, structure, prev_vasp_dir)


@dataclass
class MDMaker(BaseVaspMaker):
    """
    Maker to create VASP molecular dynamics jobs.

    Parameters
    ----------
    name : str
        The job name.
    input_set_generator : .VaspInputSetGenerator
        A generator used to make the input set.
    write_input_set_kwargs : dict
        Keyword arguments that will get passed to :obj:`.write_vasp_input_set`.
    copy_vasp_kwargs : dict
        Keyword arguments that will get passed to :obj:`.copy_vasp_outputs`.
    run_vasp_kwargs : dict
        Keyword arguments that will get passed to :obj:`.run_vasp`.
    task_document_kwargs : dict
        Keyword arguments that will get passed to :obj:`.TaskDocument.from_directory`.
    stop_children_kwargs : dict
        Keyword arguments that will get passed to :obj:`.should_stop_children`.
    write_additional_data : dict
        Additional data to write to the current directory. Given as a dict of
        {filename: data}. Note that if using FireWorks, dictionary keys cannot contain
        the "." character which is typically used to denote file extensions. To avoid
        this, use the ":" character, which will automatically be converted to ".". E.g.
        ``{"my_file:txt": "contents of the file"}``.
    """

    name: str = "molecular dynamics"

    input_set_generator: VaspInputGenerator = field(default_factory=MDSetGenerator)

    # Explicitly pass the handlers to not use the default ones. Some default handlers
    # such as PotimErrorHandler do not apply to MD runs.
    run_vasp_kwargs: dict = field(
        default_factory=lambda: {
            "handlers": (
                VaspErrorHandler(),
                MeshSymmetryErrorHandler(),
                PositiveEnergyErrorHandler(),
                FrozenJobErrorHandler(),
                StdErrHandler(),
                LargeSigmaHandler(),
                IncorrectSmearingHandler(),
            )
        }
    )

    # Store ionic steps info in a pymatgen Trajectory object instead of in the output
    # document.
    task_document_kwargs: dict = field(
        default_factory=lambda: {"store_trajectory": True}
    )