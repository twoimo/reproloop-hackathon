"""Frozen dataset split metadata and deterministic hash generator for ReproLoop.

Enforces:
- Single owned app package: com.tinyburn.reproloop.lab
- Single fault family: F01_rename_cancel_persistence (1 bug family, 3 UI variants A/B/C;
  never claimed as 5 independent bugs).
- Case IDs strictly bounded to 1..120 characters (satisfying both repro_oracle <=128
  and evaluation_metrics <=120 contracts).
- Cryptographic SHA-256 digests for task, fixture, and scenario manifests.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Literal

_EXAMPLES_DIR = str(Path(__file__).resolve().parents[1] / "examples")
if _EXAMPLES_DIR not in sys.path:
    sys.path.insert(0, _EXAMPLES_DIR)

from repro_oracle import CaseSpec, valid_digest, valid_name  # noqa: E402

PACKAGE_NAME = "com.tinyburn.reproloop.lab"
FAULT_FAMILY_ID = "F01_rename_cancel_persistence"
ORACLE_NAME = "cancel_preserves_stored_title"
NATIVE_CANDIDATE_PRESET = "Today"
NATIVE_INTERACTION_ACTIONS = ("task_open", "rename_open", "select_preset", "cancel_edit")
NATIVE_EVENT_SEQUENCE = ("fixture_loaded", "task_open", "rename_open", "select_preset", "cancel_edit")
SplitName = Literal["DEV", "PILOT", "FINAL"]
VariantName = Literal["A", "B", "C"]


def _canonical_sha256(obj: object) -> str:
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")
    return sha256(raw).hexdigest()


def deterministic_int_seed(seed_id: str) -> int:
    """Deterministically map a canonical seed_id string into FixtureSpec's 0..1,000,000 int range."""
    if not valid_name(seed_id, 64):
        raise ValueError(f"invalid seed_id: {seed_id!r}")
    digest_hex = sha256(seed_id.encode("utf-8")).hexdigest()
    return int(digest_hex[:12], 16) % 1_000_001


@dataclass(frozen=True)
class ScenarioSpec:
    case_id: str
    split: SplitName
    variant: VariantName
    fault_family: str
    package_name: str
    oracle_name: str
    seed_id: str
    initial_title: str
    candidate_preset: str
    non_target_title: str
    entry_navigation: tuple[str, ...]
    expected_actions: tuple[str, ...]
    mutable_for_tuning: bool
    task_sha256: str
    fixture_sha256: str
    scenario_sha256: str

    def validate(self) -> None:
        if not valid_name(self.case_id, 120):
            raise ValueError(f"invalid case_id (must be 1..120 stripped chars): {self.case_id!r}")
        if self.split not in ("DEV", "PILOT", "FINAL"):
            raise ValueError(f"invalid split: {self.split!r}")
        if self.variant not in ("A", "B", "C"):
            raise ValueError(f"invalid variant: {self.variant!r}")
        if self.fault_family != FAULT_FAMILY_ID:
            raise ValueError(f"unexpected fault_family: {self.fault_family!r}")
        if self.package_name != PACKAGE_NAME:
            raise ValueError(f"unexpected package_name: {self.package_name!r}")
        if self.oracle_name != ORACLE_NAME or not valid_name(self.oracle_name, 128):
            raise ValueError(f"invalid oracle_name: {self.oracle_name!r}")
        for label, val in (
            ("seed_id", self.seed_id),
            ("initial_title", self.initial_title),
            ("candidate_preset", self.candidate_preset),
            ("non_target_title", self.non_target_title),
        ):
            if not valid_name(val, 64):
                raise ValueError(f"invalid {label}: {val!r}")
        if self.initial_title == self.candidate_preset:
            raise ValueError("initial_title and candidate_preset must differ to test F01 Cancel persistence")
        if type(self.mutable_for_tuning) is not bool:
            raise ValueError("mutable_for_tuning must be exact bool")
        if self.mutable_for_tuning != (self.split == "DEV"):
            raise ValueError("only DEV scenarios may set mutable_for_tuning=True")
        if not isinstance(self.entry_navigation, tuple) or not 1 <= len(self.entry_navigation) <= 8:
            raise ValueError("invalid entry_navigation tuple")
        if not isinstance(self.expected_actions, tuple) or not 1 <= len(self.expected_actions) <= 8:
            raise ValueError("invalid expected_actions tuple")
        for digest_val in (self.task_sha256, self.fixture_sha256, self.scenario_sha256):
            if not valid_digest(digest_val):
                raise ValueError(f"invalid 64-hex digest: {digest_val!r}")

        expected_task_hash = _canonical_sha256({
            "package_name": self.package_name,
            "fault_family": self.fault_family,
            "variant": self.variant,
            "entry_navigation": list(self.entry_navigation),
            "expected_actions": list(self.expected_actions),
            "target_initial_title": self.initial_title,
            "candidate_preset": self.candidate_preset,
        })
        expected_fixture_hash = _canonical_sha256({
            "package_name": self.package_name,
            "seed_id": self.seed_id,
            "variant": self.variant,
            "tasks": [
                {"id": "task_target", "title": self.initial_title, "role": "target"},
                {"id": "task_other", "title": self.non_target_title, "role": "non_target_invariant"},
            ],
            "candidate_preset": self.candidate_preset,
        })
        expected_scenario_hash = _canonical_sha256({
            "case_id": self.case_id,
            "split": self.split,
            "variant": self.variant,
            "seed_id": self.seed_id,
            "mutable_for_tuning": self.mutable_for_tuning,
            "task_sha256": expected_task_hash,
            "fixture_sha256": expected_fixture_hash,
            "oracle_name": self.oracle_name,
        })
        if self.task_sha256 != expected_task_hash:
            raise ValueError(f"task_sha256 mismatch for {self.case_id}")
        if self.fixture_sha256 != expected_fixture_hash:
            raise ValueError(f"fixture_sha256 mismatch for {self.case_id}")
        if self.scenario_sha256 != expected_scenario_hash:
            raise ValueError(f"scenario_sha256 mismatch for {self.case_id}")

    def to_case_spec(self, faulty_build_sha256: str, repaired_build_sha256: str) -> CaseSpec:
        self.validate()
        if not valid_digest(faulty_build_sha256) or not valid_digest(repaired_build_sha256):
            raise ValueError("build digests must be 64-char lowercase hex")
        return CaseSpec(
            case_id=self.case_id,
            task_sha256=self.task_sha256,
            fixture_sha256=self.fixture_sha256,
            faulty_build_sha256=faulty_build_sha256,
            repaired_build_sha256=repaired_build_sha256,
            oracle_name=self.oracle_name,
        )


@dataclass(frozen=True)
class SplitManifest:
    schema_version: int
    package_name: str
    fault_family: str
    bug_family_count: int
    ui_variant_count: int
    generalization_scope: str
    scenarios: tuple[ScenarioSpec, ...]
    manifest_sha256: str

    def by_split(self, split: SplitName) -> tuple[ScenarioSpec, ...]:
        return tuple(s for s in self.scenarios if s.split == split)

    def planned_case_ids(self, split: SplitName) -> list[str]:
        return [s.case_id for s in self.by_split(split)]

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "package_name": self.package_name,
            "fault_family": self.fault_family,
            "bug_family_count": self.bug_family_count,
            "ui_variant_count": self.ui_variant_count,
            "generalization_scope": self.generalization_scope,
            "counts": {
                "DEV": len(self.by_split("DEV")),
                "PILOT": len(self.by_split("PILOT")),
                "FINAL": len(self.by_split("FINAL")),
                "total": len(self.scenarios),
            },
            "scenarios": [
                {
                    **asdict(s),
                    "entry_navigation": list(s.entry_navigation),
                    "expected_actions": list(s.expected_actions),
                }
                for s in self.scenarios
            ],
            "manifest_sha256": self.manifest_sha256,
        }


def _make_scenario(
    case_id: str,
    split: SplitName,
    variant: VariantName,
    seed_id: str,
    initial_title: str,
    candidate_preset: str,
    non_target_title: str,
) -> ScenarioSpec:
    if variant == "A":
        entry_nav = ("list_root", "open_rename_dialog_direct")
    elif variant == "B":
        entry_nav = ("list_reordered", "open_rename_dialog_reordered_chips")
    elif variant == "C":
        entry_nav = ("list_root", "open_task_detail_screen", "open_rename_dialog_relocated_cancel")
    else:
        raise ValueError(f"unsupported variant: {variant!r}")

    actions = ("open_rename", f"select_preset_{candidate_preset}", "cancel")
    mutable = (split == "DEV")

    task_sha = _canonical_sha256({
        "package_name": PACKAGE_NAME,
        "fault_family": FAULT_FAMILY_ID,
        "variant": variant,
        "entry_navigation": list(entry_nav),
        "expected_actions": list(actions),
        "target_initial_title": initial_title,
        "candidate_preset": candidate_preset,
    })
    fixture_sha = _canonical_sha256({
        "package_name": PACKAGE_NAME,
        "seed_id": seed_id,
        "variant": variant,
        "tasks": [
            {"id": "task_target", "title": initial_title, "role": "target"},
            {"id": "task_other", "title": non_target_title, "role": "non_target_invariant"},
        ],
        "candidate_preset": candidate_preset,
    })
    scenario_sha = _canonical_sha256({
        "case_id": case_id,
        "split": split,
        "variant": variant,
        "seed_id": seed_id,
        "mutable_for_tuning": mutable,
        "task_sha256": task_sha,
        "fixture_sha256": fixture_sha,
        "oracle_name": ORACLE_NAME,
    })
    spec = ScenarioSpec(
        case_id=case_id,
        split=split,
        variant=variant,
        fault_family=FAULT_FAMILY_ID,
        package_name=PACKAGE_NAME,
        oracle_name=ORACLE_NAME,
        seed_id=seed_id,
        initial_title=initial_title,
        candidate_preset=candidate_preset,
        non_target_title=non_target_title,
        entry_navigation=entry_nav,
        expected_actions=actions,
        mutable_for_tuning=mutable,
        task_sha256=task_sha,
        fixture_sha256=fixture_sha,
        scenario_sha256=scenario_sha,
    )
    spec.validate()
    return spec


def build_frozen_splits() -> SplitManifest:
    """Construct the canonical DEV (2), PILOT (5), and FINAL (3) scenario splits."""
    scenarios = (
        # DEV split (2 scenarios, Variant A) — tuning permitted only here
        _make_scenario("DEV-01", "DEV", "A", "seed-dev-01-a", "Inbox", "Today", "Errands"),
        _make_scenario("DEV-02", "DEV", "A", "seed-dev-02-a", "Backlog", "Urgent", "Reading"),
        # PILOT split (5 scenarios: 2 Variant A, 2 Variant B, 1 Variant C) — frozen for Day 1.5 gate
        _make_scenario("P01", "PILOT", "A", "seed-pilot-01-a", "Inbox", "Today", "Groceries"),
        _make_scenario("P02", "PILOT", "A", "seed-pilot-02-a", "Drafts", "Archive", "Taxes"),
        _make_scenario("P03", "PILOT", "B", "seed-pilot-03-b", "Inbox", "Later", "Invoices"),
        _make_scenario("P04", "PILOT", "B", "seed-pilot-04-b", "Sprint", "Blocked", "Roadmap"),
        _make_scenario("P05", "PILOT", "C", "seed-pilot-05-c", "Inbox", "Someday", "Receipts"),
        # FINAL split (3 scenarios: 1 per Variant A/B/C) — frozen for final regression repeats
        _make_scenario("FINAL-A", "FINAL", "A", "seed-final-01-a", "Release", "Hold", "Changelog"),
        _make_scenario("FINAL-B", "FINAL", "B", "seed-final-02-b", "Release", "Hold", "Changelog"),
        _make_scenario("FINAL-C", "FINAL", "C", "seed-final-03-c", "Release", "Hold", "Changelog"),
    )
    body = [
        {
            **asdict(s),
            "entry_navigation": list(s.entry_navigation),
            "expected_actions": list(s.expected_actions),
        }
        for s in scenarios
    ]
    manifest_sha = _canonical_sha256({
        "schema_version": 1,
        "package_name": PACKAGE_NAME,
        "fault_family": FAULT_FAMILY_ID,
        "bug_family_count": 1,
        "ui_variant_count": 3,
        "scenarios": body,
    })
    manifest = SplitManifest(
        schema_version=1,
        package_name=PACKAGE_NAME,
        fault_family=FAULT_FAMILY_ID,
        bug_family_count=1,
        ui_variant_count=3,
        generalization_scope=(
            "Single fault family F01 (Cancel in rename dialog wrongly persists draft title) "
            "across 3 UI layout/navigation variants (A, B, C) in owned app com.tinyburn.reproloop.lab. "
            "Does NOT measure cross-app or multi-bug-family generalization."
        ),
        scenarios=scenarios,
        manifest_sha256=manifest_sha,
    )
    verify_split_integrity(manifest)
    return manifest


def verify_split_integrity(manifest: SplitManifest) -> None:
    if type(manifest) is not SplitManifest:
        raise ValueError("typed SplitManifest required")
    if manifest.schema_version != 1:
        raise ValueError("unsupported SplitManifest schema_version")
    if manifest.package_name != PACKAGE_NAME or manifest.fault_family != FAULT_FAMILY_ID:
        raise ValueError("package_name or fault_family mismatch")
    if manifest.bug_family_count != 1 or manifest.ui_variant_count != 3:
        raise ValueError("ReproLoop MVP must declare exactly 1 bug family and 3 UI variants")
    if not isinstance(manifest.scenarios, tuple) or len(manifest.scenarios) != 10:
        raise ValueError("expected exactly 10 frozen scenarios (2 DEV, 5 PILOT, 3 FINAL)")

    seen_ids: set[str] = set()
    seen_seeds: set[str] = set()
    seen_fixtures: set[str] = set()
    for s in manifest.scenarios:
        if type(s) is not ScenarioSpec:
            raise ValueError("typed ScenarioSpec required")
        s.validate()
        if s.case_id in seen_ids:
            raise ValueError(f"duplicate case_id: {s.case_id}")
        if s.seed_id in seen_seeds:
            raise ValueError(f"duplicate seed_id: {s.seed_id}")
        if s.fixture_sha256 in seen_fixtures:
            raise ValueError(f"duplicate fixture_sha256 across scenarios: {s.case_id}")
        seen_ids.add(s.case_id)
        seen_seeds.add(s.seed_id)
        seen_fixtures.add(s.fixture_sha256)

    if [s.case_id for s in manifest.by_split("DEV")] != ["DEV-01", "DEV-02"]:
        raise ValueError("DEV split IDs must be ['DEV-01', 'DEV-02']")
    if [s.case_id for s in manifest.by_split("PILOT")] != ["P01", "P02", "P03", "P04", "P05"]:
        raise ValueError("PILOT split IDs must be ['P01', 'P02', 'P03', 'P04', 'P05']")
    if [s.case_id for s in manifest.by_split("FINAL")] != ["FINAL-A", "FINAL-B", "FINAL-C"]:
        raise ValueError("FINAL split IDs must be ['FINAL-A', 'FINAL-B', 'FINAL-C']")

    body = [
        {
            **asdict(s),
            "entry_navigation": list(s.entry_navigation),
            "expected_actions": list(s.expected_actions),
        }
        for s in manifest.scenarios
    ]
    expected_sha = _canonical_sha256({
        "schema_version": 1,
        "package_name": PACKAGE_NAME,
        "fault_family": FAULT_FAMILY_ID,
        "bug_family_count": 1,
        "ui_variant_count": 3,
        "scenarios": body,
    })
    if not valid_digest(manifest.manifest_sha256) or manifest.manifest_sha256 != expected_sha:
        raise ValueError("SplitManifest digest mismatch")


def get_scenario(case_id: str, manifest: SplitManifest | None = None) -> ScenarioSpec:
    m = build_frozen_splits() if manifest is None else manifest
    verify_split_integrity(m)
    for s in m.scenarios:
        if s.case_id == case_id:
            return s
    raise KeyError(f"unknown scenario case_id: {case_id!r}")


@dataclass(frozen=True)
class NativeScenario:
    """Live v2 scenario aligned byte-for-byte with runtime.app_state.FixtureSpec and android-contract.md."""
    case_id: str
    fixture_id: str
    split: SplitName
    layout_variant: VariantName
    fault_family: str
    package_name: str
    oracle_name: str
    seed_id: str
    seed: int
    target_id: str
    target_title: str
    non_target_id: str
    non_target_title: str
    candidate_preset: str
    expected_Faulty_after_title: str
    expected_Fixed_after_title: str
    interaction_actions: tuple[str, ...]
    expected_event_actions: tuple[str, ...]
    mutable_for_tuning: bool
    task_sha256: str
    fixture_sha256: str
    scenario_sha256: str

    def fixture_fields(self) -> dict:
        """Exact canonical dictionary hashed by runtime.app_state.FixtureSpec.sha256."""
        return dict(
            fixture_id=self.fixture_id,
            layout_variant=self.layout_variant,
            non_target_id=self.non_target_id,
            non_target_title=self.non_target_title,
            seed=self.seed,
            target_id=self.target_id,
            target_title=self.target_title,
        )

    def validate(self) -> None:
        if not valid_name(self.case_id, 120):
            raise ValueError(f"invalid case_id: {self.case_id!r}")
        if not valid_name(self.fixture_id, 64) or not all(32 < ord(c) <= 126 for c in self.fixture_id):
            raise ValueError(f"invalid fixture_id: {self.fixture_id!r}")
        if self.split not in ("DEV", "PILOT", "FINAL"):
            raise ValueError(f"invalid split: {self.split!r}")
        if self.layout_variant not in ("A", "B", "C"):
            raise ValueError(f"invalid layout_variant: {self.layout_variant!r}")
        if self.fault_family != FAULT_FAMILY_ID or self.package_name != PACKAGE_NAME:
            raise ValueError("package_name or fault_family mismatch")
        if self.oracle_name != ORACLE_NAME or not valid_name(self.oracle_name, 128):
            raise ValueError("invalid oracle_name")
        if not valid_name(self.seed_id, 64):
            raise ValueError(f"invalid seed_id: {self.seed_id!r}")
        if type(self.seed) is not int or not 0 <= self.seed <= 1_000_000:
            raise ValueError(f"seed must be int in 0..1_000_000, got {self.seed!r}")
        if self.seed != deterministic_int_seed(self.seed_id):
            raise ValueError(f"seed {self.seed} does not match deterministic_int_seed({self.seed_id!r})")
        if self.target_id != "target" or self.non_target_id != "other":
            raise ValueError("native app requires target_id='target' and non_target_id='other'")
        for label, val in (("target_title", self.target_title), ("non_target_title", self.non_target_title)):
            if type(val) is not str or not 1 <= len(val) <= 64 or val != val.strip() or not all(32 <= ord(c) <= 126 for c in val):
                raise ValueError(f"invalid printable ASCII {label}: {val!r}")
        if self.target_title == "Today":
            raise ValueError("NONDISCRIMINATING_FIXTURE: target_title must not equal 'Today'")
        if self.target_title == self.non_target_title:
            raise ValueError("target_title and non_target_title must be distinct")
        if self.candidate_preset != NATIVE_CANDIDATE_PRESET:
            raise ValueError(f"native app supports only candidate_preset='Today', got {self.candidate_preset!r}")
        if self.expected_Faulty_after_title != "Today" or self.expected_Fixed_after_title != self.target_title:
            raise ValueError("invalid expected faulty/fixed persisted titles")
        if self.interaction_actions != NATIVE_INTERACTION_ACTIONS:
            raise ValueError(f"interaction_actions must equal {NATIVE_INTERACTION_ACTIONS}")
        if self.expected_event_actions != NATIVE_EVENT_SEQUENCE:
            raise ValueError(f"expected_event_actions must equal {NATIVE_EVENT_SEQUENCE}")
        if type(self.mutable_for_tuning) is not bool or self.mutable_for_tuning != (self.split == "DEV"):
            raise ValueError("mutable_for_tuning must be True iff split == 'DEV'")

        # Exact FixtureSpec.sha256 calculation from runtime.app_state
        expected_fixture_sha = sha256(
            json.dumps(self.fixture_fields(), ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        expected_task_sha = _canonical_sha256({
            "schema_version": 2,
            "package_name": self.package_name,
            "fault_family": self.fault_family,
            "layout_variant": self.layout_variant,
            "target_id": self.target_id,
            "candidate_preset": self.candidate_preset,
            "interaction_actions": list(self.interaction_actions),
        })
        expected_scenario_sha = _canonical_sha256({
            "schema_version": 2,
            "case_id": self.case_id,
            "fixture_id": self.fixture_id,
            "split": self.split,
            "layout_variant": self.layout_variant,
            "seed_id": self.seed_id,
            "seed": self.seed,
            "mutable_for_tuning": self.mutable_for_tuning,
            "task_sha256": expected_task_sha,
            "fixture_sha256": expected_fixture_sha,
            "oracle_name": self.oracle_name,
        })
        if self.fixture_sha256 != expected_fixture_sha:
            raise ValueError(f"fixture_sha256 mismatch for {self.case_id}")
        if self.task_sha256 != expected_task_sha:
            raise ValueError(f"task_sha256 mismatch for {self.case_id}")
        if self.scenario_sha256 != expected_scenario_sha:
            raise ValueError(f"scenario_sha256 mismatch for {self.case_id}")

    def to_fixture_spec(self):
        """Instantiate runtime.app_state.FixtureSpec when runtime is on sys.path, verifying identical sha256."""
        self.validate()
        try:
            from reproloop.runtime.app_state import FixtureSpec as RuntimeFixtureSpec
            fs = RuntimeFixtureSpec(
                fixture_id=self.fixture_id,
                seed=self.seed,
                layout_variant=self.layout_variant,
                target_title=self.target_title,
                non_target_title=self.non_target_title,
            )
            if fs.sha256 != self.fixture_sha256:
                raise AssertionError(f"RuntimeFixtureSpec.sha256 {fs.sha256} != {self.fixture_sha256}")
            return fs
        except ImportError:
            return self.fixture_fields()

    def to_case_spec(self, faulty_build_sha256: str, repaired_build_sha256: str) -> CaseSpec:
        self.validate()
        if not valid_digest(faulty_build_sha256) or not valid_digest(repaired_build_sha256):
            raise ValueError("build digests must be 64-char lowercase hex")
        return CaseSpec(
            case_id=self.case_id,
            task_sha256=self.task_sha256,
            fixture_sha256=self.fixture_sha256,
            faulty_build_sha256=faulty_build_sha256,
            repaired_build_sha256=repaired_build_sha256,
            oracle_name=self.oracle_name,
        )


@dataclass(frozen=True)
class NativeSplitManifest:
    schema_version: int
    manifest_kind: str
    supersedes_v1_manifest_sha256: str
    v1_supersession_reason: str
    package_name: str
    fault_family: str
    bug_family_count: int
    ui_variant_count: int
    candidate_preset: str
    interaction_actions: tuple[str, ...]
    generalization_scope: str
    scenarios: tuple[NativeScenario, ...]
    manifest_sha256: str

    def by_split(self, split: SplitName) -> tuple[NativeScenario, ...]:
        return tuple(s for s in self.scenarios if s.split == split)

    def planned_case_ids(self, split: SplitName) -> list[str]:
        return [s.case_id for s in self.by_split(split)]

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "manifest_kind": self.manifest_kind,
            "supersedes_v1_manifest_sha256": self.supersedes_v1_manifest_sha256,
            "v1_supersession_reason": self.v1_supersession_reason,
            "package_name": self.package_name,
            "fault_family": self.fault_family,
            "bug_family_count": self.bug_family_count,
            "ui_variant_count": self.ui_variant_count,
            "candidate_preset": self.candidate_preset,
            "interaction_actions": list(self.interaction_actions),
            "generalization_scope": self.generalization_scope,
            "counts": {
                "DEV": len(self.by_split("DEV")),
                "PILOT": len(self.by_split("PILOT")),
                "FINAL": len(self.by_split("FINAL")),
                "total": len(self.scenarios),
            },
            "scenarios": [
                {
                    **asdict(s),
                    "fixture_fields": s.fixture_fields(),
                    "interaction_actions": list(s.interaction_actions),
                    "expected_event_actions": list(s.expected_event_actions),
                }
                for s in self.scenarios
            ],
            "manifest_sha256": self.manifest_sha256,
        }


def _make_native_scenario(
    case_id: str,
    split: SplitName,
    layout_variant: VariantName,
    seed_id: str,
    target_title: str,
    non_target_title: str,
) -> NativeScenario:
    fixture_id = case_id
    seed_int = deterministic_int_seed(seed_id)
    mutable = (split == "DEV")
    fixture_dict = dict(
        fixture_id=fixture_id,
        layout_variant=layout_variant,
        non_target_id="other",
        non_target_title=non_target_title,
        seed=seed_int,
        target_id="target",
        target_title=target_title,
    )
    fixture_sha = sha256(
        json.dumps(fixture_dict, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    task_sha = _canonical_sha256({
        "schema_version": 2,
        "package_name": PACKAGE_NAME,
        "fault_family": FAULT_FAMILY_ID,
        "layout_variant": layout_variant,
        "target_id": "target",
        "candidate_preset": NATIVE_CANDIDATE_PRESET,
        "interaction_actions": list(NATIVE_INTERACTION_ACTIONS),
    })
    scenario_sha = _canonical_sha256({
        "schema_version": 2,
        "case_id": case_id,
        "fixture_id": fixture_id,
        "split": split,
        "layout_variant": layout_variant,
        "seed_id": seed_id,
        "seed": seed_int,
        "mutable_for_tuning": mutable,
        "task_sha256": task_sha,
        "fixture_sha256": fixture_sha,
        "oracle_name": ORACLE_NAME,
    })
    scen = NativeScenario(
        case_id=case_id,
        fixture_id=fixture_id,
        split=split,
        layout_variant=layout_variant,
        fault_family=FAULT_FAMILY_ID,
        package_name=PACKAGE_NAME,
        oracle_name=ORACLE_NAME,
        seed_id=seed_id,
        seed=seed_int,
        target_id="target",
        target_title=target_title,
        non_target_id="other",
        non_target_title=non_target_title,
        candidate_preset=NATIVE_CANDIDATE_PRESET,
        expected_Faulty_after_title="Today",
        expected_Fixed_after_title=target_title,
        interaction_actions=NATIVE_INTERACTION_ACTIONS,
        expected_event_actions=NATIVE_EVENT_SEQUENCE,
        mutable_for_tuning=mutable,
        task_sha256=task_sha,
        fixture_sha256=fixture_sha,
        scenario_sha256=scenario_sha,
    )
    scen.validate()
    return scen


def build_frozen_splits_v2() -> NativeSplitManifest:
    """Construct the live-v2 preregistered scenario manifest aligned with runtime.app_state.FixtureSpec."""
    v1_sha = build_frozen_splits().manifest_sha256
    scenarios = (
        # DEV split (2 scenarios, Variant A) — tuning permitted only here
        _make_native_scenario("DEV-01", "DEV", "A", "seed-dev-01-a", "Inbox", "Errands"),
        _make_native_scenario("DEV-02", "DEV", "A", "seed-dev-02-a", "Backlog", "Reading"),
        # PILOT split (5 scenarios: 2 Variant A, 2 Variant B, 1 Variant C) — frozen before any live pilot
        _make_native_scenario("P01", "PILOT", "A", "seed-pilot-01-a", "Inbox", "Groceries"),
        _make_native_scenario("P02", "PILOT", "A", "seed-pilot-02-a", "Drafts", "Taxes"),
        _make_native_scenario("P03", "PILOT", "B", "seed-pilot-03-b", "Inbox", "Invoices"),
        _make_native_scenario("P04", "PILOT", "B", "seed-pilot-04-b", "Sprint", "Roadmap"),
        _make_native_scenario("P05", "PILOT", "C", "seed-pilot-05-c", "Inbox", "Receipts"),
        # FINAL split (3 scenarios: 1 per Variant A/B/C) — frozen for final regression repeats
        _make_native_scenario("FINAL-A", "FINAL", "A", "seed-final-01-a", "Release", "Changelog"),
        _make_native_scenario("FINAL-B", "FINAL", "B", "seed-final-02-b", "Release", "Changelog"),
        _make_native_scenario("FINAL-C", "FINAL", "C", "seed-final-03-c", "Release", "Changelog"),
    )
    body = [
        {
            **asdict(s),
            "fixture_fields": s.fixture_fields(),
            "interaction_actions": list(s.interaction_actions),
            "expected_event_actions": list(s.expected_event_actions),
        }
        for s in scenarios
    ]
    manifest_sha = _canonical_sha256({
        "schema_version": 2,
        "manifest_kind": "LIVE_NATIVE_APP_PREREGISTRATION_V2",
        "supersedes_v1_manifest_sha256": v1_sha,
        "package_name": PACKAGE_NAME,
        "fault_family": FAULT_FAMILY_ID,
        "bug_family_count": 1,
        "ui_variant_count": 3,
        "candidate_preset": NATIVE_CANDIDATE_PRESET,
        "interaction_actions": list(NATIVE_INTERACTION_ACTIONS),
        "scenarios": body,
    })
    manifest = NativeSplitManifest(
        schema_version=2,
        manifest_kind="LIVE_NATIVE_APP_PREREGISTRATION_V2",
        supersedes_v1_manifest_sha256=v1_sha,
        v1_supersession_reason=(
            "Historical v1 (frozen-splits-v1.json) used synthetic multi-preset names and a synthetic "
            "fixture dictionary prior to reading runtime.app_state.FixtureSpec. Live v2 aligns all 10 "
            "scenarios to the owned Android app's single 'Today' preset, 4 explicit cancel-flow actions "
            "('task_open','rename_open','select_preset','cancel_edit'), and exact FixtureSpec.sha256 fields "
            "before any live pilot run is executed."
        ),
        package_name=PACKAGE_NAME,
        fault_family=FAULT_FAMILY_ID,
        bug_family_count=1,
        ui_variant_count=3,
        candidate_preset=NATIVE_CANDIDATE_PRESET,
        interaction_actions=NATIVE_INTERACTION_ACTIONS,
        generalization_scope=(
            "Single fault family F01 (Cancel in rename dialog after selecting 'Today' preset wrongly "
            "persists 'Today' instead of preserving initial target_title) across 3 UI variants (A, B, C) "
            "in owned app com.tinyburn.reproloop.lab. Primary M1 requires the same exported script to "
            "replay within each scenario's faulty/fixed pair (same layout_variant), not cross-variant export."
        ),
        scenarios=scenarios,
        manifest_sha256=manifest_sha,
    )
    verify_split_integrity_v2(manifest)
    return manifest


def verify_split_integrity_v2(manifest: NativeSplitManifest) -> None:
    if type(manifest) is not NativeSplitManifest:
        raise ValueError("typed NativeSplitManifest required")
    if manifest.schema_version != 2 or manifest.manifest_kind != "LIVE_NATIVE_APP_PREREGISTRATION_V2":
        raise ValueError("unsupported NativeSplitManifest schema_version or kind")
    if manifest.package_name != PACKAGE_NAME or manifest.fault_family != FAULT_FAMILY_ID:
        raise ValueError("package_name or fault_family mismatch")
    if manifest.bug_family_count != 1 or manifest.ui_variant_count != 3:
        raise ValueError("ReproLoop MVP must declare 1 bug family and 3 UI variants")
    if manifest.candidate_preset != NATIVE_CANDIDATE_PRESET or manifest.interaction_actions != NATIVE_INTERACTION_ACTIONS:
        raise ValueError("native preset or interaction_actions mismatch")
    if not isinstance(manifest.scenarios, tuple) or len(manifest.scenarios) != 10:
        raise ValueError("expected exactly 10 frozen scenarios (2 DEV, 5 PILOT, 3 FINAL)")

    seen_ids: set[str] = set()
    seen_fixture_ids: set[str] = set()
    seen_seed_ids: set[str] = set()
    seen_int_seeds: set[int] = set()
    seen_fixture_shas: set[str] = set()

    for s in manifest.scenarios:
        if type(s) is not NativeScenario:
            raise ValueError("typed NativeScenario required")
        s.validate()
        if s.case_id in seen_ids:
            raise ValueError(f"duplicate case_id: {s.case_id}")
        if s.fixture_id in seen_fixture_ids:
            raise ValueError(f"duplicate fixture_id: {s.fixture_id}")
        if s.seed_id in seen_seed_ids:
            raise ValueError(f"duplicate seed_id: {s.seed_id}")
        if s.seed in seen_int_seeds:
            raise ValueError(f"integer seed collision on {s.seed} for {s.case_id}")
        if s.fixture_sha256 in seen_fixture_shas:
            raise ValueError(f"duplicate fixture_sha256 for {s.case_id}")
        seen_ids.add(s.case_id)
        seen_fixture_ids.add(s.fixture_id)
        seen_seed_ids.add(s.seed_id)
        seen_int_seeds.add(s.seed)
        seen_fixture_shas.add(s.fixture_sha256)

    if [s.case_id for s in manifest.by_split("DEV")] != ["DEV-01", "DEV-02"]:
        raise ValueError("DEV split IDs must be ['DEV-01', 'DEV-02']")
    if [s.case_id for s in manifest.by_split("PILOT")] != ["P01", "P02", "P03", "P04", "P05"]:
        raise ValueError("PILOT split IDs must be ['P01', 'P02', 'P03', 'P04', 'P05']")
    if [s.case_id for s in manifest.by_split("FINAL")] != ["FINAL-A", "FINAL-B", "FINAL-C"]:
        raise ValueError("FINAL split IDs must be ['FINAL-A', 'FINAL-B', 'FINAL-C']")

    body = [
        {
            **asdict(s),
            "fixture_fields": s.fixture_fields(),
            "interaction_actions": list(s.interaction_actions),
            "expected_event_actions": list(s.expected_event_actions),
        }
        for s in manifest.scenarios
    ]
    expected_sha = _canonical_sha256({
        "schema_version": 2,
        "manifest_kind": "LIVE_NATIVE_APP_PREREGISTRATION_V2",
        "supersedes_v1_manifest_sha256": manifest.supersedes_v1_manifest_sha256,
        "package_name": PACKAGE_NAME,
        "fault_family": FAULT_FAMILY_ID,
        "bug_family_count": 1,
        "ui_variant_count": 3,
        "candidate_preset": NATIVE_CANDIDATE_PRESET,
        "interaction_actions": list(NATIVE_INTERACTION_ACTIONS),
        "scenarios": body,
    })
    if not valid_digest(manifest.manifest_sha256) or manifest.manifest_sha256 != expected_sha:
        raise ValueError("NativeSplitManifest digest mismatch")


def get_native_scenario(case_id: str, manifest: NativeSplitManifest | None = None) -> NativeScenario:
    m = build_frozen_splits_v2() if manifest is None else manifest
    verify_split_integrity_v2(m)
    for s in m.scenarios:
        if s.case_id == case_id:
            return s
    raise KeyError(f"unknown native scenario case_id: {case_id!r}")
