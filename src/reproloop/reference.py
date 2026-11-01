"""Developer-authored F01/B1 reference. Not a video/model transcription."""
from evaluation.splits import get_native_scenario
from replay_contracts import SemanticExport, Locator
from .lab import local_build_pins


def reference_export(case_id, faulty_sha, fixed_sha):
    local_build_pins({'faulty': faulty_sha, 'fixed': fixed_sha})
    scenario = get_native_scenario(case_id)
    spec = scenario.to_case_spec(faulty_sha, fixed_sha)
    steps = (('task_target', 'Target task: ' + scenario.target_title, 'tasks'),
             ('rename_open', 'Rename', 'selected'),
             ('preset_today', 'Today', 'rename'),
             ('cancel_edit', 'Cancel', 'rename'))
    return SemanticExport(scenario.package_name, spec.task_sha256, spec.fixture_sha256,
                          tuple(Locator(scenario.package_name + ':id/' + rid, text, screen)
                                for rid, text, screen in steps))
