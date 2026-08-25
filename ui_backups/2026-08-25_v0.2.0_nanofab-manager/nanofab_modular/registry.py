from __future__ import annotations

from .step_api import ProcessStepModule
from .steps.cleaning_step import CleaningStep
from .steps.development_step import DevelopmentStep
from .steps.lift_off_step import LiftOffStep
from .steps.projection_exposure_step import ProjectionExposureStep
from .steps.resist_coating_step import ResistCoatingStep
from .steps.soft_bake_step import SoftBakeStep
from .steps.substrate_selection_step import SubstrateSelectionStep
from .steps.thin_film_deposition_step import ThinFilmDepositionStep


def build_default_modules() -> list[ProcessStepModule]:
    return [
        SubstrateSelectionStep(),
        CleaningStep(),
        ResistCoatingStep(),
        SoftBakeStep(),
        ProjectionExposureStep(),
        DevelopmentStep(),
        ThinFilmDepositionStep(),
        LiftOffStep(),
    ]
